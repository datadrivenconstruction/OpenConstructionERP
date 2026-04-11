/**
 * BIMViewer — Three.js-based 3D BIM viewer component.
 *
 * Renders BIM model elements as colored 3D boxes (by discipline), supports
 * click/hover selection, wireframe toggle, zoom-to-fit, and a properties panel.
 *
 * NOTE: Requires `three` and `@types/three` npm packages.
 */

import { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  Home,
  Grid3X3,
  Box,
  Eye,
  EyeOff,
  Maximize2,
  Loader2,
  AlertCircle,
  Link2,
  Link2Off,
  Plus,
  Camera,
  Square,
  CornerUpLeft,
  FileText,
  CheckSquare,
  Calendar,
  ExternalLink,
  ShieldCheck,
  ShieldAlert,
  ShieldX,
} from 'lucide-react';
import { SceneManager } from './SceneManager';
import { ElementManager } from './ElementManager';
import type { BIMElementData } from './ElementManager';
import { SelectionManager } from './SelectionManager';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type BIMViewMode = 'default' | '5d_cost' | '4d_schedule' | 'discipline';

export interface BIMViewerProps {
  /** BIM model ID to load. */
  modelId: string;
  /** Project ID. */
  projectId: string;
  /** Element IDs to highlight (controlled selection from parent). */
  selectedElementIds?: string[];
  /** Callback when an element is clicked. */
  onElementSelect?: (elementId: string | null) => void;
  /** Callback when an element is hovered. */
  onElementHover?: (elementId: string | null) => void;
  /** View mode coloring scheme. */
  viewMode?: BIMViewMode;
  /** Show measurement tools. */
  showMeasureTools?: boolean;
  /** Additional CSS class. */
  className?: string;
  /** Elements to render (loaded externally by the parent). */
  elements?: BIMElementData[];
  /** Loading state (from parent). */
  isLoading?: boolean;
  /** Error message (from parent). */
  error?: string | null;
  /** URL to DAE/COLLADA geometry file (served from backend). */
  geometryUrl?: string | null;
  /**
   * Optional visibility predicate. When set, the viewer calls
   * ElementManager.applyFilter(predicate) so only matching elements stay
   * visible. Fast — no re-render, just mesh.visible toggles.
   */
  filterPredicate?: ((el: BIMElementData) => boolean) | null;
  /**
   * Color-by mode. ``'default'`` uses discipline colors, other modes recolor
   * meshes based on the chosen element field via a golden-angle palette.
   */
  colorByMode?: 'default' | 'discipline' | 'storey' | 'type';
  /** Element IDs to isolate (hide everything else). Empty = show all. */
  isolatedIds?: string[] | null;
  /** Element IDs to highlight in orange WITHOUT hiding the rest of the
   *  model — used to show which BIM elements are linked to the currently
   *  selected BOQ position.  Pass null/empty to clear. */
  highlightedIds?: string[] | null;
  /**
   * Called once DAE geometry finishes loading, with the ratio of elements
   * whose mesh was successfully matched by stable_id/name (0..1). The
   * parent uses this to warn users when per-element filters cannot affect
   * the viewport (e.g. DDC RVT exports with numeric node names).
   */
  onGeometryLoaded?: (meshMatchRatio: number) => void;
  /** User clicked "Add to BOQ" on the selected element — parent opens the
   *  AddToBOQModal pre-filled with this element. */
  onAddToBOQ?: (element: BIMElementData) => void;
  /** User clicked "Unlink" on a specific link in the properties panel. */
  onUnlinkBOQ?: (linkId: string) => void;
  /** User clicked a linked document in the properties panel — parent
   *  navigates to /documents/{id} or opens an embedded preview. */
  onOpenDocument?: (documentId: string) => void;
  /** User clicked a linked task in the properties panel. */
  onOpenTask?: (taskId: string) => void;
  /** User clicked a linked schedule activity in the properties panel. */
  onOpenActivity?: (activityId: string) => void;
  /** User clicked "+ New" in the Linked Tasks section — parent opens
   *  CreateTaskFromBIMModal pre-filled with this element. */
  onCreateTask?: (element: BIMElementData) => void;
  /** User clicked "+ Link" in the Linked Documents section — parent opens
   *  the LinkDocumentToBIMModal picker. */
  onLinkDocument?: (element: BIMElementData) => void;
  /** User clicked "+ Link" in the Schedule Activities section. */
  onLinkActivity?: (element: BIMElementData) => void;
}

/* ── Properties Table ──────────────────────────────────────────────────── */

function PropertiesTable({ properties }: { properties: Record<string, unknown> }) {
  const entries = Object.entries(properties).filter(([, v]) => v != null && v !== '');
  if (entries.length === 0) return null;

  return (
    <table className="w-full text-xs">
      <tbody>
        {entries.map(([key, value]) => (
          <tr key={key} className="border-b border-border-light last:border-0">
            <td className="py-1 pe-2 text-content-tertiary font-medium whitespace-nowrap">
              {key}
            </td>
            <td className="py-1 text-content-secondary break-all">{String(value)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function QuantitiesTable({ quantities }: { quantities: Record<string, number> }) {
  const entries = Object.entries(quantities).filter(([, v]) => v != null);
  if (entries.length === 0) return null;

  return (
    <table className="w-full text-xs">
      <tbody>
        {entries.map(([key, value]) => (
          <tr key={key} className="border-b border-border-light last:border-0">
            <td className="py-1 pe-2 text-content-tertiary font-medium whitespace-nowrap">
              {key}
            </td>
            <td className="py-1 text-content-secondary tabular-nums text-end">
              {typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 3 }) : String(value)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ── BIM Viewer Component ──────────────────────────────────────────────── */

export function BIMViewer({
  modelId,
  projectId: _projectId,
  selectedElementIds,
  onElementSelect,
  onElementHover,
  viewMode: _viewMode = 'default',
  showMeasureTools: _showMeasureTools = false,
  className,
  elements,
  isLoading = false,
  error = null,
  geometryUrl = null,
  filterPredicate = null,
  colorByMode = 'default',
  isolatedIds = null,
  highlightedIds = null,
  onGeometryLoaded,
  onAddToBOQ,
  onUnlinkBOQ,
  onOpenDocument,
  onOpenTask,
  onOpenActivity,
  onCreateTask,
  onLinkDocument,
  onLinkActivity,
}: BIMViewerProps) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sceneRef = useRef<SceneManager | null>(null);
  const elementMgrRef = useRef<ElementManager | null>(null);
  const selectionMgrRef = useRef<SelectionManager | null>(null);

  const [wireframe, setWireframe] = useState(false);
  const [gridVisible, setGridVisible] = useState(true);
  const [selectedElement, setSelectedElement] = useState<BIMElementData | null>(null);
  const [elementCount, setElementCount] = useState(0);

  /** Number of elements that have at least one BOQ link.  Derived from
   *  the elements prop so it updates whenever the parent re-fetches after
   *  a link is created or deleted. */
  const linkedCount = useMemo(
    () => (elements ?? []).filter((el) => (el.boq_links?.length ?? 0) > 0).length,
    [elements],
  );

  // Initialize Three.js scene on mount
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const scene = new SceneManager(canvas);
    sceneRef.current = scene;

    const elementMgr = new ElementManager(scene);
    elementMgrRef.current = elementMgr;

    const selectionMgr = new SelectionManager(scene, elementMgr, {
      onElementSelect: (id) => {
        if (id) {
          const data = elementMgr.getElementData(id);
          setSelectedElement(data ?? null);
        } else {
          setSelectedElement(null);
        }
        onElementSelect?.(id);
      },
      onElementHover: (id) => {
        onElementHover?.(id);
      },
    });
    selectionMgrRef.current = selectionMgr;

    return () => {
      selectionMgr.dispose();
      elementMgr.dispose();
      scene.dispose();
      sceneRef.current = null;
      elementMgrRef.current = null;
      selectionMgrRef.current = null;
    };
    // Intentionally only run on mount — stable refs
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-wire callbacks when handlers change (avoid stale closures)
  const onElementSelectRef = useRef(onElementSelect);
  onElementSelectRef.current = onElementSelect;
  const onElementHoverRef = useRef(onElementHover);
  onElementHoverRef.current = onElementHover;

  // Load elements when data changes. When a real DAE/COLLADA geometry
  // URL is available we skip the placeholder boxes — the placeholders
  // would briefly render at the BIM bounding-box coordinates (which are
  // in source-CAD units, often a different scale than the COLLADA scene)
  // and trigger a wrong-distance camera fit before the DAE finishes
  // loading. Skipping them keeps the first zoomToFit clean.
  useEffect(() => {
    if (!elementMgrRef.current || !elements) return;
    const skipPlaceholders = !!geometryUrl;
    elementMgrRef.current.loadElements(elements, { skipPlaceholders });
    setElementCount(elements.length);
  }, [elements, geometryUrl]);

  // Load DAE geometry when URL is available (after elements are loaded)
  const onGeometryLoadedRef = useRef(onGeometryLoaded);
  onGeometryLoadedRef.current = onGeometryLoaded;
  useEffect(() => {
    if (!elementMgrRef.current || !geometryUrl || !elements?.length) return;
    const mgr = elementMgrRef.current;
    // Only load if not already loaded for this URL
    if (!mgr.hasLoadedGeometry()) {
      mgr
        .loadDAEGeometry(geometryUrl)
        .then(() => {
          onGeometryLoadedRef.current?.(mgr.getMeshMatchRatio());
          // Re-fit the camera AFTER the DAE scene has been parented and
          // the next render cycle had a chance to commit world matrices.
          // We schedule three fits at increasing delays as belt & braces:
          //   * 0  ms — synchronous, catches the common case
          //   * 50 ms — lets ColladaLoader's microtasks settle
          //   * 250ms — ultimate safety net for slow first-frame layouts
          // Each call inside SceneManager.zoomToFit forces
          // updateMatrixWorld(true), so a stale matrix tree cannot
          // sabotage the bbox computation.
          const fit = () => sceneRef.current?.zoomToFit();
          fit();
          setTimeout(fit, 50);
          setTimeout(fit, 250);
        })
        .catch(() => {
          // Silently fall back to placeholder boxes (already rendered by loadElements)
        });
    }
  }, [geometryUrl, elements]);

  // Apply filter predicate whenever it changes. Predicates from BIMFilterPanel
  // are rebuilt on every filter state change, so this effect fires fast but
  // only toggles mesh.visible — no geometry regeneration.
  //
  // After applying, we ZOOM the camera to the visible subset so the user gets
  // immediate spatial feedback. For models where mesh ↔ element mapping is
  // approximate (DDC RVT exports without stable IDs), the zoom gives the
  // user a tangible "the filter did something" signal even when the per-mesh
  // visibility isn't perfectly accurate.
  useEffect(() => {
    if (!elementMgrRef.current || !sceneRef.current) return;
    if (isolatedIds && isolatedIds.length > 0) {
      elementMgrRef.current.isolate(isolatedIds);
      const visibleMeshes = elementMgrRef.current
        .getAllMeshes()
        .filter((m) => m.visible);
      if (visibleMeshes.length > 0) {
        sceneRef.current.zoomToSelection(visibleMeshes);
      }
    } else if (filterPredicate) {
      const visibleCount = elementMgrRef.current.applyFilter(filterPredicate);
      if (visibleCount > 0 && visibleCount < elementMgrRef.current.getAllMeshes().length) {
        const visibleMeshes = elementMgrRef.current
          .getAllMeshes()
          .filter((m) => m.visible);
        if (visibleMeshes.length > 0) {
          sceneRef.current.zoomToSelection(visibleMeshes);
        }
      } else if (visibleCount === elementMgrRef.current.getAllMeshes().length) {
        // All visible (e.g. cleared filter) — zoom back out to the full model
        sceneRef.current.zoomToFit();
      }
    } else {
      elementMgrRef.current.showAll();
      sceneRef.current.zoomToFit();
    }
  }, [filterPredicate, isolatedIds, elements]);

  // Highlight linked elements in orange when the parent passes a set of
  // IDs.  Unlike isolate(), this does NOT hide the rest of the model —
  // it just recolours the matched meshes so the user sees the spatial
  // distribution of whichever BOQ position they're inspecting.
  useEffect(() => {
    if (!elementMgrRef.current) return;
    elementMgrRef.current.highlight(highlightedIds ?? []);
  }, [highlightedIds, elements]);

  // Apply color-by mode when it changes.
  useEffect(() => {
    if (!elementMgrRef.current || !elements?.length) return;
    const mgr = elementMgrRef.current;
    if (colorByMode === 'storey') {
      mgr.colorBy((el) => el.storey || 'Unassigned');
    } else if (colorByMode === 'type') {
      mgr.colorBy((el) => el.element_type || 'Unknown');
    } else {
      mgr.resetColors();
    }
  }, [colorByMode, elements]);

  // Sync selection from parent
  useEffect(() => {
    if (!selectionMgrRef.current || !selectedElementIds) return;
    selectionMgrRef.current.setSelection(selectedElementIds);

    // Update the properties panel for the first selected element
    if (selectedElementIds.length > 0 && elementMgrRef.current) {
      const data = elementMgrRef.current.getElementData(selectedElementIds[0]!);
      setSelectedElement(data ?? null);
    }
  }, [selectedElementIds]);

  // Toolbar actions
  const handleZoomToFit = useCallback(() => {
    sceneRef.current?.zoomToFit();
  }, []);

  const handleToggleWireframe = useCallback(() => {
    elementMgrRef.current?.toggleWireframe();
    setWireframe((prev) => !prev);
  }, []);

  const handleZoomToSelection = useCallback(() => {
    const selMgr = selectionMgrRef.current;
    const elMgr = elementMgrRef.current;
    const scene = sceneRef.current;
    if (!selMgr || !elMgr || !scene) return;

    const ids = selMgr.getSelectedIds();
    const meshes = ids
      .map((id) => elMgr.getMesh(id))
      .filter((m): m is NonNullable<typeof m> => m != null);
    if (meshes.length > 0) {
      scene.zoomToSelection(meshes);
    }
  }, []);

  const handleCloseProperties = useCallback(() => {
    setSelectedElement(null);
    selectionMgrRef.current?.clearSelection();
    onElementSelect?.(null);
  }, [onElementSelect]);

  const handleToggleGrid = useCallback(() => {
    sceneRef.current?.toggleGrid();
    setGridVisible((v) => !v);
  }, []);

  const handleCameraPreset = useCallback((view: 'top' | 'front' | 'side' | 'iso') => {
    sceneRef.current?.setCameraPreset(view);
  }, []);

  // Memoize the element properties/quantities for the panel
  const elementProperties = useMemo(() => {
    if (!selectedElement?.properties) return {};
    return selectedElement.properties;
  }, [selectedElement]);

  const elementQuantities = useMemo(() => {
    if (!selectedElement?.quantities) return {};
    return selectedElement.quantities;
  }, [selectedElement]);

  return (
    <div className={clsx('relative w-full h-full min-h-[400px] bg-surface-secondary rounded-lg overflow-hidden', className)}>
      <canvas ref={canvasRef} className="w-full h-full block" />

      {/* Loading overlay */}
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-surface-secondary/80 backdrop-blur-sm z-10">
          <div className="flex flex-col items-center gap-3">
            <Loader2 size={32} className="animate-spin text-oe-blue" />
            <span className="text-sm text-content-secondary">
              {t('bim.loading_model', { defaultValue: 'Loading model...' })}
            </span>
          </div>
        </div>
      )}

      {/* Error overlay */}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-surface-secondary/80 z-10">
          <div className="flex flex-col items-center gap-3 text-center px-8">
            <AlertCircle size={32} className="text-red-500" />
            <span className="text-sm text-content-secondary">{error}</span>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && elementCount === 0 && modelId && (
        <div className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
          <div className="flex flex-col items-center gap-2 text-center">
            <Box size={40} className="text-content-tertiary" />
            <span className="text-sm text-content-tertiary">
              {t('bim.no_elements', { defaultValue: 'No elements to display' })}
            </span>
          </div>
        </div>
      )}

      {/* Toolbar overlay — organised by function group with dividers.
          Grouping follows the professional 6-group taxonomy from the research
          brief: Camera | Selection | Visibility | (contextual tools follow). */}
      <div className="absolute top-3 start-3 flex items-center gap-1 z-20 rounded-lg bg-surface-primary/90 backdrop-blur border border-border-light shadow-sm p-1">
        {/* Camera group — presets + fit */}
        <ToolbarButton
          icon={Home}
          label={t('bim.zoom_fit', { defaultValue: 'Fit all' })}
          onClick={handleZoomToFit}
          variant="group"
        />
        <ToolbarButton
          icon={Box}
          label={t('bim.view_iso', { defaultValue: 'Isometric view' })}
          onClick={() => handleCameraPreset('iso')}
          variant="group"
        />
        <ToolbarButton
          icon={Square}
          label={t('bim.view_top', { defaultValue: 'Top view' })}
          onClick={() => handleCameraPreset('top')}
          variant="group"
        />
        <ToolbarButton
          icon={CornerUpLeft}
          label={t('bim.view_front', { defaultValue: 'Front view' })}
          onClick={() => handleCameraPreset('front')}
          variant="group"
        />
        <ToolbarButton
          icon={Camera}
          label={t('bim.view_side', { defaultValue: 'Side view' })}
          onClick={() => handleCameraPreset('side')}
          variant="group"
        />
        <div className="w-px h-5 bg-border-light mx-0.5" />
        {/* Selection group */}
        <ToolbarButton
          icon={Maximize2}
          label={t('bim.zoom_selection', { defaultValue: 'Zoom to selection' })}
          onClick={handleZoomToSelection}
          variant="group"
        />
        <div className="w-px h-5 bg-border-light mx-0.5" />
        {/* Visibility group */}
        <ToolbarButton
          icon={Grid3X3}
          label={t('bim.wireframe', { defaultValue: 'Wireframe' })}
          onClick={handleToggleWireframe}
          active={wireframe}
          variant="group"
        />
        <ToolbarButton
          icon={gridVisible ? Eye : EyeOff}
          label={
            gridVisible
              ? t('bim.hide_grid', { defaultValue: 'Hide grid' })
              : t('bim.show_grid', { defaultValue: 'Show grid' })
          }
          onClick={handleToggleGrid}
          active={gridVisible}
          variant="group"
        />
      </div>

      {/* Element count + link-progress badge. Shows total element count
          plus a "N linked" chip (green) that counts how many elements
          have at least one BOQ link — gives the user at-a-glance progress
          on the takeoff workflow. */}
      {elementCount > 0 && (
        <div className="absolute top-3 end-3 z-20 flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-surface-primary/90 backdrop-blur text-content-secondary border border-border-light shadow-sm">
            <Box size={12} />
            {t('bim.element_count', { defaultValue: '{{count}} elements', count: elementCount })}
          </span>
          {linkedCount > 0 && (
            <span
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200 shadow-sm"
              title={t('bim.linked_count_title', {
                defaultValue: '{{linked}} of {{total}} elements are linked to a BOQ position',
                linked: linkedCount,
                total: elementCount,
              })}
            >
              <Link2 size={12} />
              {t('bim.linked_count', { defaultValue: '{{count}} linked', count: linkedCount })}
            </span>
          )}
        </div>
      )}

      {/* Properties panel (when element selected) */}
      {selectedElement && (
        <div className="absolute top-12 end-3 w-72 bg-surface-primary/95 backdrop-blur border border-border-light rounded-lg shadow-lg z-20 max-h-[calc(100%-6rem)] overflow-y-auto">
          <div className="flex items-center justify-between p-3 border-b border-border-light">
            <h3 className="text-sm font-semibold text-content-primary truncate">
              {selectedElement.name || selectedElement.element_type || selectedElement.id}
            </h3>
            <button
              onClick={handleCloseProperties}
              className="flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:bg-surface-secondary transition-colors"
              aria-label={t('common.close', { defaultValue: 'Close' })}
            >
              <span className="text-xs font-bold">&times;</span>
            </button>
          </div>

          <div className="p-3 space-y-3">
            {/* Element info */}
            <div className="space-y-1">
              <InfoRow
                label={t('bim.prop_type', { defaultValue: 'Type' })}
                value={selectedElement.element_type}
              />
              <InfoRow
                label={t('bim.prop_discipline', { defaultValue: 'Discipline' })}
                value={selectedElement.discipline}
              />
              {selectedElement.storey && (
                <InfoRow
                  label={t('bim.prop_storey', { defaultValue: 'Storey' })}
                  value={selectedElement.storey}
                />
              )}
              {selectedElement.category && (
                <InfoRow
                  label={t('bim.prop_category', { defaultValue: 'Category' })}
                  value={selectedElement.category}
                />
              )}
            </div>

            {/* Classification */}
            {selectedElement.classification && Object.keys(selectedElement.classification).length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-content-primary mb-1">
                  {t('bim.classification', { defaultValue: 'Classification' })}
                </h4>
                <PropertiesTable properties={selectedElement.classification} />
              </div>
            )}

            {/* Quantities */}
            {Object.keys(elementQuantities).length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-content-primary mb-1">
                  {t('bim.quantities', { defaultValue: 'Quantities' })}
                </h4>
                <QuantitiesTable quantities={elementQuantities} />
              </div>
            )}

            {/* Validation results — appears when the user has run
                POST /validation/check-bim-model on this model.  Each
                element gets a per-element rollup (pass/warning/error)
                plus the list of failed rules with messages. */}
            {selectedElement.validation_results && selectedElement.validation_results.length > 0 && (
              <div
                className={`rounded-md border p-2 ${
                  selectedElement.validation_status === 'error'
                    ? 'border-rose-300/60 bg-rose-50/50 dark:bg-rose-950/20'
                    : selectedElement.validation_status === 'warning'
                      ? 'border-amber-300/60 bg-amber-50/50 dark:bg-amber-950/20'
                      : 'border-emerald-300/60 bg-emerald-50/50 dark:bg-emerald-950/20'
                }`}
              >
                <h4
                  className={`text-xs font-semibold flex items-center gap-1 mb-1.5 ${
                    selectedElement.validation_status === 'error'
                      ? 'text-rose-700 dark:text-rose-300'
                      : selectedElement.validation_status === 'warning'
                        ? 'text-amber-700 dark:text-amber-300'
                        : 'text-emerald-700 dark:text-emerald-300'
                  }`}
                >
                  {selectedElement.validation_status === 'error' ? (
                    <ShieldX size={11} />
                  ) : selectedElement.validation_status === 'warning' ? (
                    <ShieldAlert size={11} />
                  ) : (
                    <ShieldCheck size={11} />
                  )}
                  {t('bim.validation_results', { defaultValue: 'Validation results' })}
                  <span className="text-[10px] text-content-tertiary font-normal">
                    ({selectedElement.validation_results.length})
                  </span>
                </h4>
                <ul className="space-y-0.5">
                  {selectedElement.validation_results.slice(0, 6).map((vr, i) => (
                    <li
                      key={`${vr.rule_id}-${i}`}
                      className="flex items-start gap-1.5 text-[10px] text-content-secondary"
                    >
                      <span
                        className={`mt-0.5 inline-block h-1.5 w-1.5 rounded-full shrink-0 ${
                          vr.severity === 'error'
                            ? 'bg-rose-500'
                            : vr.severity === 'warning'
                              ? 'bg-amber-500'
                              : 'bg-sky-500'
                        }`}
                      />
                      <div className="min-w-0 flex-1">
                        <div
                          className="text-content-primary truncate"
                          title={vr.rule_id}
                        >
                          {vr.rule_id}
                        </div>
                        <div className="text-content-tertiary text-[9px] line-clamp-2">
                          {vr.message}
                        </div>
                      </div>
                    </li>
                  ))}
                  {selectedElement.validation_results.length > 6 && (
                    <li className="text-[9px] text-content-tertiary italic">
                      + {selectedElement.validation_results.length - 6} more rules
                    </li>
                  )}
                </ul>
              </div>
            )}

            {/* BOQ Links — the headline integration feature.
                Shows every BOQ position this element is linked to, with an
                "Unlink" action on each, plus an "Add to BOQ" button that
                opens the AddToBOQModal in the parent. */}
            <div className="rounded-md border border-oe-blue/30 bg-oe-blue/5 p-2">
              <div className="flex items-center justify-between mb-1.5">
                <h4 className="text-xs font-semibold text-oe-blue flex items-center gap-1">
                  <Link2 size={11} />
                  {t('bim.linked_boq', { defaultValue: 'Linked BOQ positions' })}
                  {selectedElement.boq_links && selectedElement.boq_links.length > 0 && (
                    <span className="text-[10px] text-content-tertiary font-normal">
                      ({selectedElement.boq_links.length})
                    </span>
                  )}
                </h4>
                {onAddToBOQ && (
                  <button
                    type="button"
                    onClick={() => onAddToBOQ(selectedElement)}
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-oe-blue text-white hover:bg-oe-blue-dark"
                    title={t('bim.link_add_title', { defaultValue: 'Add this element to a BOQ position' })}
                  >
                    <Plus size={10} />
                    {t('bim.link_add', { defaultValue: 'Add to BOQ' })}
                  </button>
                )}
              </div>
              {selectedElement.boq_links && selectedElement.boq_links.length > 0 ? (
                <ul className="space-y-1">
                  {selectedElement.boq_links.map((link) => (
                    <li
                      key={link.id}
                      className="flex items-center justify-between gap-1 px-1.5 py-1 rounded bg-surface-primary border border-border-light"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          {link.boq_position_ordinal && (
                            <span className="text-[10px] font-mono font-semibold text-content-primary tabular-nums">
                              {link.boq_position_ordinal}
                            </span>
                          )}
                          <span
                            className={`text-[9px] px-1 rounded ${
                              link.link_type === 'manual'
                                ? 'bg-emerald-100 text-emerald-700'
                                : link.link_type === 'rule_based'
                                  ? 'bg-violet-100 text-violet-700'
                                  : 'bg-sky-100 text-sky-700'
                            }`}
                          >
                            {link.link_type.replace('_', ' ')}
                          </span>
                        </div>
                        <div className="text-[11px] text-content-secondary truncate" title={link.boq_position_description || ''}>
                          {link.boq_position_description || '—'}
                        </div>
                      </div>
                      {onUnlinkBOQ && (
                        <button
                          type="button"
                          onClick={() => onUnlinkBOQ(link.id)}
                          className="p-1 rounded text-content-tertiary hover:text-rose-600 hover:bg-rose-50"
                          title={t('bim.link_remove', { defaultValue: 'Remove link' })}
                        >
                          <Link2Off size={11} />
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="text-[10px] text-content-tertiary italic">
                  {t('bim.link_empty', {
                    defaultValue: 'Not linked — click "Add to BOQ" to link this element to a cost position',
                  })}
                </div>
              )}
            </div>

            {/* Linked Documents — always rendered when callbacks present
                so users can ADD links from an empty state too. */}
            {(onLinkDocument || (selectedElement.linked_documents && selectedElement.linked_documents.length > 0)) && (
              <div className="rounded-md border border-violet-300/50 bg-violet-50/40 dark:bg-violet-950/20 p-2">
                <div className="flex items-center justify-between mb-1.5">
                  <h4 className="text-xs font-semibold text-violet-700 dark:text-violet-300 flex items-center gap-1">
                    <FileText size={11} />
                    {t('bim.linked_documents', { defaultValue: 'Linked documents' })}
                    <span className="text-[10px] text-content-tertiary font-normal">
                      ({selectedElement.linked_documents?.length ?? 0})
                    </span>
                  </h4>
                  {onLinkDocument && (
                    <button
                      type="button"
                      onClick={() => onLinkDocument(selectedElement)}
                      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-violet-600 text-white hover:bg-violet-700"
                      title={t('bim.link_doc', { defaultValue: 'Link a document to this element' })}
                    >
                      <Plus size={10} />
                      {t('bim.link', { defaultValue: 'Link' })}
                    </button>
                  )}
                </div>
                {selectedElement.linked_documents && selectedElement.linked_documents.length > 0 ? (
                  <ul className="space-y-1">
                    {selectedElement.linked_documents.map((d) => (
                      <li
                        key={d.id}
                        className="flex items-center justify-between gap-1 px-1.5 py-1 rounded bg-surface-primary border border-border-light"
                      >
                        <button
                          type="button"
                          onClick={() => onOpenDocument?.(d.document_id)}
                          className="flex-1 min-w-0 text-left"
                        >
                          <div className="text-[11px] text-content-primary truncate" title={d.document_name || ''}>
                            {d.document_name || '—'}
                          </div>
                          {d.document_category && (
                            <div className="text-[9px] text-content-tertiary uppercase tracking-wider">
                              {d.document_category}
                            </div>
                          )}
                        </button>
                        <ExternalLink size={10} className="text-content-tertiary shrink-0" />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="text-[10px] text-content-tertiary italic">
                    {t('bim.docs_empty', {
                      defaultValue: 'No drawings linked yet — click "Link" to attach a drawing or photo',
                    })}
                  </div>
                )}
              </div>
            )}

            {/* Linked Tasks — always rendered when callback present. */}
            {(onCreateTask || (selectedElement.linked_tasks && selectedElement.linked_tasks.length > 0)) && (
              <div className="rounded-md border border-amber-300/50 bg-amber-50/40 dark:bg-amber-950/20 p-2">
                <div className="flex items-center justify-between mb-1.5">
                  <h4 className="text-xs font-semibold text-amber-700 dark:text-amber-300 flex items-center gap-1">
                    <CheckSquare size={11} />
                    {t('bim.linked_tasks', { defaultValue: 'Linked tasks' })}
                    <span className="text-[10px] text-content-tertiary font-normal">
                      ({selectedElement.linked_tasks?.length ?? 0})
                    </span>
                  </h4>
                  {onCreateTask && (
                    <button
                      type="button"
                      onClick={() => onCreateTask(selectedElement)}
                      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-600 text-white hover:bg-amber-700"
                      title={t('bim.create_task', { defaultValue: 'Create a task pinned to this element' })}
                    >
                      <Plus size={10} />
                      {t('bim.new', { defaultValue: 'New' })}
                    </button>
                  )}
                </div>
                {selectedElement.linked_tasks && selectedElement.linked_tasks.length > 0 ? (
                  <ul className="space-y-1">
                    {selectedElement.linked_tasks.map((task) => (
                      <li
                        key={task.id}
                        className="flex items-center justify-between gap-1 px-1.5 py-1 rounded bg-surface-primary border border-border-light"
                      >
                        <button
                          type="button"
                          onClick={() => onOpenTask?.(task.id)}
                          className="flex-1 min-w-0 text-left"
                        >
                          <div className="flex items-center gap-1.5">
                            <span
                              className={`text-[9px] px-1 rounded uppercase tracking-wider ${
                                task.status === 'closed' || task.status === 'done'
                                  ? 'bg-emerald-100 text-emerald-700'
                                  : task.status === 'in_progress'
                                    ? 'bg-sky-100 text-sky-700'
                                    : 'bg-amber-100 text-amber-700'
                              }`}
                            >
                              {task.status}
                            </span>
                            {task.task_type && (
                              <span className="text-[9px] text-content-tertiary">{task.task_type}</span>
                            )}
                          </div>
                          <div className="text-[11px] text-content-primary truncate" title={task.title}>
                            {task.title}
                          </div>
                        </button>
                        <ExternalLink size={10} className="text-content-tertiary shrink-0" />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="text-[10px] text-content-tertiary italic">
                    {t('bim.tasks_empty', {
                      defaultValue: 'No tasks pinned yet — click "New" to file a defect or RFI',
                    })}
                  </div>
                )}
              </div>
            )}

            {/* Schedule Activities (4D) — always rendered when callback present. */}
            {(onLinkActivity || (selectedElement.linked_activities && selectedElement.linked_activities.length > 0)) && (
              <div className="rounded-md border border-emerald-300/50 bg-emerald-50/40 dark:bg-emerald-950/20 p-2">
                <div className="flex items-center justify-between mb-1.5">
                  <h4 className="text-xs font-semibold text-emerald-700 dark:text-emerald-300 flex items-center gap-1">
                    <Calendar size={11} />
                    {t('bim.linked_activities', { defaultValue: 'Schedule activities (4D)' })}
                    <span className="text-[10px] text-content-tertiary font-normal">
                      ({selectedElement.linked_activities?.length ?? 0})
                    </span>
                  </h4>
                  {onLinkActivity && (
                    <button
                      type="button"
                      onClick={() => onLinkActivity(selectedElement)}
                      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-600 text-white hover:bg-emerald-700"
                      title={t('bim.link_activity', { defaultValue: 'Link a schedule activity to this element' })}
                    >
                      <Plus size={10} />
                      {t('bim.link', { defaultValue: 'Link' })}
                    </button>
                  )}
                </div>
                {selectedElement.linked_activities && selectedElement.linked_activities.length > 0 ? (
                  <ul className="space-y-1">
                    {selectedElement.linked_activities.map((act) => (
                      <li
                        key={act.id}
                        className="flex items-center justify-between gap-1 px-1.5 py-1 rounded bg-surface-primary border border-border-light"
                      >
                        <button
                          type="button"
                          onClick={() => onOpenActivity?.(act.id)}
                          className="flex-1 min-w-0 text-left"
                        >
                          <div className="text-[11px] text-content-primary truncate" title={act.name}>
                            {act.name}
                          </div>
                          <div className="flex items-center gap-1.5 text-[9px] text-content-tertiary tabular-nums">
                            {act.start_date && <span>{act.start_date.slice(0, 10)}</span>}
                            {act.start_date && act.end_date && <span>→</span>}
                            {act.end_date && <span>{act.end_date.slice(0, 10)}</span>}
                            {typeof act.percent_complete === 'number' && (
                              <span className="ms-auto font-medium">{act.percent_complete}%</span>
                            )}
                          </div>
                        </button>
                        <ExternalLink size={10} className="text-content-tertiary shrink-0" />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="text-[10px] text-content-tertiary italic">
                    {t('bim.acts_empty', {
                      defaultValue: 'No 4D activities yet — click "Link" to attach a schedule activity',
                    })}
                  </div>
                )}
              </div>
            )}

            {/* Properties */}
            {Object.keys(elementProperties).length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-content-primary mb-1">
                  {t('bim.properties', { defaultValue: 'Properties' })}
                </h4>
                <PropertiesTable properties={elementProperties} />
              </div>
            )}
          </div>
        </div>
      )}

      {/* Note: the old bottom-left view-mode selector (Default / Discipline /
          5D Cost / 4D Schedule) has been removed in v1.3.22.  It was a
          visual-only stub with no backend — the 5D and 4D modes were never
          wired to cost or schedule data.  Coloring by discipline / storey /
          type now lives in the top toolbar of BIMPage via the colorByMode
          dropdown, which is the single source of truth. */}
    </div>
  );
}

/* ── Shared Sub-components ─────────────────────────────────────────────── */

function ToolbarButton({
  icon: Icon,
  label,
  onClick,
  active = false,
  variant = 'standalone',
}: {
  icon: React.ElementType;
  label: string;
  onClick: () => void;
  active?: boolean;
  /** `standalone` renders with its own background + border + shadow.
   *  `group` renders flat so it slots into a shared container (the reorganised
   *  toolbar wraps every button in one bordered row). */
  variant?: 'standalone' | 'group';
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      className={clsx(
        'flex h-7 w-7 items-center justify-center rounded transition-colors',
        variant === 'standalone' && 'shadow-sm border bg-surface-primary/90 backdrop-blur border-border-light',
        active
          ? 'bg-oe-blue text-white' + (variant === 'standalone' ? ' border-oe-blue' : '')
          : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
      )}
    >
      <Icon size={14} />
    </button>
  );
}

function InfoRow({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div className="flex items-baseline gap-2 text-xs">
      <span className="text-content-tertiary font-medium shrink-0">{label}:</span>
      <span className="text-content-secondary truncate">{value}</span>
    </div>
  );
}

/* ── Discipline Visibility Toggle ──────────────────────────────────────── */

export function DisciplineToggle({
  disciplines,
  visible,
  onToggle,
}: {
  disciplines: string[];
  visible: Record<string, boolean>;
  onToggle: (discipline: string) => void;
}) {
  const { t } = useTranslation();
  if (disciplines.length === 0) return null;

  return (
    <div className="space-y-1">
      <h4 className="text-xs font-semibold text-content-primary">
        {t('bim.disciplines', { defaultValue: 'Disciplines' })}
      </h4>
      {disciplines.map((d) => {
        const isVisible = visible[d] !== false;
        return (
          <button
            key={d}
            onClick={() => onToggle(d)}
            className="flex items-center gap-2 w-full text-xs px-2 py-1 rounded hover:bg-surface-secondary transition-colors"
          >
            {isVisible ? (
              <Eye size={14} className="text-oe-blue" />
            ) : (
              <EyeOff size={14} className="text-content-tertiary" />
            )}
            <span className={clsx(isVisible ? 'text-content-primary' : 'text-content-tertiary')}>
              {d}
            </span>
          </button>
        );
      })}
    </div>
  );
}
