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

/* ── View Mode Selector ────────────────────────────────────────────────── */

function ViewModeSelector({
  value,
  onChange,
}: {
  value: BIMViewMode;
  onChange: (mode: BIMViewMode) => void;
}) {
  const { t } = useTranslation();
  const modes: { id: BIMViewMode; label: string }[] = [
    { id: 'default', label: t('bim.view_default', { defaultValue: 'Default' }) },
    { id: 'discipline', label: t('bim.view_discipline', { defaultValue: 'Discipline' }) },
    { id: '5d_cost', label: t('bim.view_5d', { defaultValue: '5D Cost' }) },
    { id: '4d_schedule', label: t('bim.view_4d', { defaultValue: '4D Schedule' }) },
  ];

  return (
    <div className="flex bg-surface-primary/90 backdrop-blur rounded-lg border border-border-light shadow-sm">
      {modes.map((mode) => (
        <button
          key={mode.id}
          onClick={() => onChange(mode.id)}
          className={clsx(
            'px-3 py-1.5 text-xs font-medium transition-colors first:rounded-s-lg last:rounded-e-lg',
            value === mode.id
              ? 'bg-oe-blue text-white'
              : 'text-content-secondary hover:bg-surface-secondary',
          )}
        >
          {mode.label}
        </button>
      ))}
    </div>
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
}: BIMViewerProps) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sceneRef = useRef<SceneManager | null>(null);
  const elementMgrRef = useRef<ElementManager | null>(null);
  const selectionMgrRef = useRef<SelectionManager | null>(null);

  const [wireframe, setWireframe] = useState(false);
  const [internalViewMode, setInternalViewMode] = useState<BIMViewMode>(_viewMode);
  const [selectedElement, setSelectedElement] = useState<BIMElementData | null>(null);
  const [elementCount, setElementCount] = useState(0);

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

  // Load elements when data changes
  useEffect(() => {
    if (!elementMgrRef.current || !elements) return;
    elementMgrRef.current.loadElements(elements);
    setElementCount(elements.length);
  }, [elements]);

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

      {/* Toolbar overlay */}
      <div className="absolute top-3 start-3 flex gap-1.5 z-20">
        <ToolbarButton
          icon={Home}
          label={t('bim.zoom_fit', { defaultValue: 'Fit all' })}
          onClick={handleZoomToFit}
        />
        <ToolbarButton
          icon={Grid3X3}
          label={t('bim.wireframe', { defaultValue: 'Wireframe' })}
          onClick={handleToggleWireframe}
          active={wireframe}
        />
        <ToolbarButton
          icon={Maximize2}
          label={t('bim.zoom_selection', { defaultValue: 'Zoom to selection' })}
          onClick={handleZoomToSelection}
        />
      </div>

      {/* Element count badge */}
      {elementCount > 0 && (
        <div className="absolute top-3 end-3 z-20">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-surface-primary/90 backdrop-blur text-content-secondary border border-border-light shadow-sm">
            <Box size={12} />
            {t('bim.element_count', { defaultValue: '{{count}} elements', count: elementCount })}
          </span>
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

      {/* View mode controls */}
      <div className="absolute bottom-3 start-3 z-20">
        <ViewModeSelector value={internalViewMode} onChange={setInternalViewMode} />
      </div>
    </div>
  );
}

/* ── Shared Sub-components ─────────────────────────────────────────────── */

function ToolbarButton({
  icon: Icon,
  label,
  onClick,
  active = false,
}: {
  icon: React.ElementType;
  label: string;
  onClick: () => void;
  active?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      className={clsx(
        'flex h-8 w-8 items-center justify-center rounded-lg transition-colors shadow-sm border',
        active
          ? 'bg-oe-blue text-white border-oe-blue'
          : 'bg-surface-primary/90 backdrop-blur text-content-secondary border-border-light hover:bg-surface-secondary hover:text-content-primary',
      )}
    >
      <Icon size={16} />
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
