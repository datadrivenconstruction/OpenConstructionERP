// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BIMToolsPanel - Tools tab of the BIM right panel (RFC 19).
 *
 * Hosts three tool families:
 *   1. Measure distance - on/off toggle. The active flag is held in
 *      `useBIMViewerStore`, the BIMViewer wires it to the MeasureManager.
 *      The completed-measurements list mirrors `useBIMMeasurementsStore`
 *      so users can rename / hide / focus / delete past measurements
 *      after they leave measure mode (RFC 19 §UX-9, §UX-10).
 *   2. Saved views / camera bookmarks - backed by SavedViewsStore
 *      (localStorage, 100-viewpoints-per-model cap). Supports rename
 *      (pencil) and delete (trash) (§UX-6).
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Ruler, Camera, Trash2, Play, Pencil, Check, X, Eye, EyeOff, Crosshair, Image as ImageIcon, FileSpreadsheet, FileBarChart } from 'lucide-react';
import {
  listViewpoints,
  removeViewpoint,
  renameViewpoint,
  addViewpoint,
  type Viewpoint,
  type SavedBIMFilterState,
  type BIMClipState,
} from '@/shared/ui/BIMViewer';
import { useBIMViewerStore } from '@/stores/useBIMViewerStore';
import { useBIMMeasurementsStore, type StoredMeasurement } from '@/stores/useBIMMeasurementsStore';
import { useToastStore } from '@/stores/useToastStore';
import { useDisplayQuantity } from '@/shared/hooks/useDisplayQuantity';
import {
  exportBoqXlsx,
  buildBoqExportBody,
  type BoqExportContext,
  type BoqExportScope,
  type BoqGroupBy,
} from './api';
import { fmtFixed, getIntlLocale } from '@/shared/lib/formatters';

interface BIMToolsPanelProps {
  modelId: string;
  /** Current camera snapshot - provided by the parent so we don't need a
   *  direct handle on the SceneManager. */
  getCurrentViewpoint: () => {
    position: { x: number; y: number; z: number };
    target: { x: number; y: number; z: number };
  } | null;
  /** Current filter-panel snapshot, captured at save time alongside the
   *  camera so the viewpoint round-trips the full inspection context. */
  getCurrentFilterState?: () => SavedBIMFilterState | null;
  /** Current ClipManager snapshot (section box / cutting plane). */
  getCurrentClipState?: () => BIMClipState | null;
  /** Capture a small PNG thumbnail of the current viewport. The data-URL is
   *  stored verbatim on the viewpoint and rendered as a 96×64 preview. */
  getCurrentScreenshot?: (opts?: { width?: number; height?: number }) => string | null;
  /** Move the camera to a stored viewpoint (and apply its filter / clip if
   *  the viewpoint carries them). */
  onApplyViewpoint: (vp: Viewpoint) => void;
  /** Resolve the live export context (current selection + active filter) at
   *  click time so the BOQ export reflects what the user has on screen.
   *  Optional - when absent the Export section exports the whole model. */
  getExportContext?: () => BoqExportContext;
  /** Open the on-screen quantity report for the chosen scope. Optional -
   *  the button is only shown when the parent wires this. */
  onOpenReport?: (scope: BoqExportScope, groupBy: BoqGroupBy) => void;
}

export default function BIMToolsPanel({
  modelId,
  getCurrentViewpoint,
  getCurrentFilterState,
  getCurrentClipState,
  getCurrentScreenshot,
  onApplyViewpoint,
  getExportContext,
  onOpenReport,
}: BIMToolsPanelProps) {
  const { t } = useTranslation();
  // Display-only metric->imperial conversion for saved measurement distances
  // (#270). The stored measurement distance stays metric-canonical (metres).
  const q = useDisplayQuantity();
  const measureActive = useBIMViewerStore((s) => s.measureActive);
  const setMeasureActive = useBIMViewerStore((s) => s.setMeasureActive);
  const measurements = useBIMMeasurementsStore((s) => s.measurements);
  const removeMeasurement = useBIMMeasurementsStore((s) => s.remove);
  const clearMeasurements = useBIMMeasurementsStore((s) => s.clear);
  const renameMeasurement = useBIMMeasurementsStore((s) => s.rename);
  const setMeasurementVisible = useBIMMeasurementsStore((s) => s.setVisible);

  const [views, setViews] = useState<Viewpoint[]>([]);
  const [name, setName] = useState('');
  const [exportScope, setExportScope] = useState<BoqExportScope>('all');
  const [exportGroupBy, setExportGroupBy] = useState<BoqGroupBy>('element_type');
  const [exporting, setExporting] = useState(false);
  const [quotaWarning, setQuotaWarning] = useState(false);
  const [editingViewId, setEditingViewId] = useState<string | null>(null);
  const [editingViewDraft, setEditingViewDraft] = useState('');
  const [editingMeasureId, setEditingMeasureId] = useState<string | null>(null);
  const [editingMeasureDraft, setEditingMeasureDraft] = useState('');
  /** When true, ``handleSave`` also attaches a 320×180 thumbnail to the
   *  viewpoint. Defaults to ON so the first save is informative; the user
   *  can disable for camera-only bookmarks (smaller localStorage payload). */
  const [includeScreenshot, setIncludeScreenshot] = useState(true);

  const refresh = useCallback(() => {
    setViews(listViewpoints(modelId));
  }, [modelId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleSave = useCallback(() => {
    const snapshot = getCurrentViewpoint();
    if (!snapshot) return;
    const fallback = new Date().toLocaleString(getIntlLocale());
    // Capture the rest of the viewer state at the moment of save - filter
    // panel selections, section box / clipping plane, and an optional
    // thumbnail. Each is best-effort: if the bridge isn't installed (e.g.
    // unit-test harness mounts the panel standalone) we just store the
    // camera, keeping back-compat with the v3.11.0 payload shape.
    const filterState = getCurrentFilterState?.() ?? undefined;
    const clipState = getCurrentClipState?.() ?? undefined;
    let screenshotDataUrl: string | undefined;
    if (includeScreenshot && getCurrentScreenshot) {
      // 320×180 keeps each PNG roughly 30-60 KB - 100 views ≈ 6 MB per
      // model, well under the typical localStorage cap. Failures fall
      // back to a camera-only save (the user still gets the bookmark).
      try {
        const thumb = getCurrentScreenshot({ width: 320, height: 180 });
        screenshotDataUrl = thumb ?? undefined;
      } catch {
        screenshotDataUrl = undefined;
      }
    }

    const result = addViewpoint(modelId, {
      name: (name.trim() || fallback).slice(0, 80),
      cameraPos: [snapshot.position.x, snapshot.position.y, snapshot.position.z],
      target: [snapshot.target.x, snapshot.target.y, snapshot.target.z],
      ...(filterState ? { filterState } : {}),
      ...(clipState ? { clipState } : {}),
      ...(screenshotDataUrl ? { screenshotDataUrl } : {}),
    });
    setQuotaWarning(result.quotaExceeded);
    setName('');
    refresh();
  }, [
    getCurrentViewpoint,
    getCurrentFilterState,
    getCurrentClipState,
    getCurrentScreenshot,
    includeScreenshot,
    modelId,
    name,
    refresh,
  ]);

  const handleRemove = useCallback(
    (id: string) => {
      removeViewpoint(modelId, id);
      refresh();
    },
    [modelId, refresh],
  );

  const handleStartRename = useCallback((v: Viewpoint) => {
    setEditingViewId(v.id);
    setEditingViewDraft(v.name);
  }, []);

  const handleConfirmRename = useCallback(() => {
    if (!editingViewId) return;
    renameViewpoint(modelId, editingViewId, editingViewDraft);
    setEditingViewId(null);
    setEditingViewDraft('');
    refresh();
  }, [editingViewId, editingViewDraft, modelId, refresh]);

  const handleCancelRename = useCallback(() => {
    setEditingViewId(null);
    setEditingViewDraft('');
  }, []);

  // ── Measurement-row actions are routed through `window.__oeBim` so the
  // panel doesn't need a direct MeasureManager handle. The bridge is
  // installed by BIMViewer at mount; if the viewer isn't mounted (e.g.
  // panel rendered standalone in a unit test) the calls are no-ops.
  const bridge = (): {
    removeMeasurement?: (id: string) => void;
    clearMeasurements?: () => void;
    setMeasurementVisible?: (id: string, visible: boolean) => void;
    focusMeasurement?: (id: string) => void;
  } | null => {
    return (
      (window as unknown as { __oeBim?: ReturnType<typeof bridge> }).__oeBim ?? null
    );
  };

  const handleDeleteMeasurement = useCallback(
    (id: string) => {
      bridge()?.removeMeasurement?.(id);
      removeMeasurement(id);
    },
    [removeMeasurement],
  );

  const handleClearMeasurements = useCallback(() => {
    bridge()?.clearMeasurements?.();
    clearMeasurements();
  }, [clearMeasurements]);

  const handleToggleMeasurementVisible = useCallback(
    (m: StoredMeasurement) => {
      const next = !m.visible;
      bridge()?.setMeasurementVisible?.(m.id, next);
      setMeasurementVisible(m.id, next);
    },
    [setMeasurementVisible],
  );

  const handleFocusMeasurement = useCallback((id: string) => {
    bridge()?.focusMeasurement?.(id);
  }, []);

  const handleExportBoq = useCallback(async () => {
    const ctx = getExportContext?.() ?? { selectedIds: [], filters: null };
    // Guard the two scoped modes so the user never silently gets a whole-model
    // export when they meant "just what I selected / filtered".
    if (exportScope === 'selected' && ctx.selectedIds.length === 0) {
      useToastStore.getState().addToast({
        type: 'warning',
        title: t('bim.boq_export_no_selection', { defaultValue: 'Nothing selected' }),
        message: t('bim.boq_export_no_selection_msg', {
          defaultValue: 'Select one or more elements in the model, or switch the scope to the whole model.',
        }),
      });
      return;
    }
    if (exportScope === 'filter' && !ctx.filters) {
      useToastStore.getState().addToast({
        type: 'warning',
        title: t('bim.boq_export_no_filter', { defaultValue: 'No filter applied' }),
        message: t('bim.boq_export_no_filter_msg', {
          defaultValue: 'Apply a storey or type filter first, or switch the scope to the whole model.',
        }),
      });
      return;
    }
    setExporting(true);
    try {
      await exportBoqXlsx(modelId, buildBoqExportBody(exportScope, exportGroupBy, ctx));
      useToastStore.getState().addToast({
        type: 'success',
        title: t('bim.boq_export_done', { defaultValue: 'BOQ exported' }),
        message: t('bim.boq_export_done_msg', {
          defaultValue: 'The Bill of Quantities spreadsheet has been downloaded.',
        }),
      });
    } catch (e) {
      useToastStore.getState().addToast({
        type: 'error',
        title: t('bim.boq_export_failed', { defaultValue: 'BOQ export failed' }),
        message: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setExporting(false);
    }
  }, [getExportContext, exportScope, exportGroupBy, modelId, t]);

  return (
    <div className="flex flex-col gap-4 p-3">
      {/* Measure */}
      <section className="flex flex-col gap-2">
        <h3 className="text-xs font-semibold text-content-primary uppercase tracking-wide">
          {t('bim.tools_measure_title', { defaultValue: 'Measure' })}
        </h3>
        <button
          type="button"
          onClick={() => setMeasureActive(!measureActive)}
          aria-pressed={measureActive}
          data-testid="measure-toggle"
          className={`flex items-center justify-center gap-2 px-3 py-1.5 rounded-md text-[11px] font-medium border ${
            measureActive
              ? 'bg-oe-blue/10 text-oe-blue border-oe-blue/40'
              : 'bg-surface-secondary text-content-secondary border-border-light hover:bg-surface-tertiary'
          }`}
        >
          <Ruler size={12} />
          {measureActive
            ? t('bim.tools_measure_stop', { defaultValue: 'Stop measuring' })
            : t('bim.tools_measure_start', { defaultValue: 'Measure distance (M)' })}
        </button>
        <p className="text-[10px] text-content-tertiary">
          {t('bim.tools_measure_hint', {
            defaultValue: 'Click two points in the viewport to record a distance.',
          })}
        </p>

        {/* Measurement list - completed measurements survive Stop and live
            here until the user deletes them. RFC 19 §UX-9 / §UX-10. */}
        {measurements.length > 0 && (
          <div className="mt-1 flex items-center justify-between">
            <span className="text-[10px] text-content-tertiary">
              {t('bim.tools_measure_count', {
                defaultValue: '{{count}} saved',
                count: measurements.length,
              })}
            </span>
            <button
              type="button"
              onClick={handleClearMeasurements}
              className="text-[10px] text-rose-600 hover:underline"
              data-testid="measure-clear-all"
            >
              {t('bim.tools_measure_clear_all', {
                defaultValue: 'Clear all measurements',
              })}
            </button>
          </div>
        )}
        <ul
          className="flex flex-col gap-1"
          data-testid="measurements-list"
        >
          {measurements.map((m) => {
            const isEditing = editingMeasureId === m.id;
            return (
              <li
                key={m.id}
                className="flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-2 py-1 min-w-0"
                data-testid="measurement-row"
              >
                {isEditing ? (
                  <>
                    <input
                      type="text"
                      value={editingMeasureDraft}
                      onChange={(e) => setEditingMeasureDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          renameMeasurement(m.id, editingMeasureDraft);
                          setEditingMeasureId(null);
                        }
                        if (e.key === 'Escape') setEditingMeasureId(null);
                      }}
                      autoFocus
                      className="flex-1 min-w-0 rounded border border-border-light bg-surface-secondary px-1 py-0.5 text-[11px]"
                    />
                    <button
                      type="button"
                      onClick={() => {
                        renameMeasurement(m.id, editingMeasureDraft);
                        setEditingMeasureId(null);
                      }}
                      className="inline-flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:bg-surface-tertiary hover:text-emerald-600 shrink-0"
                      aria-label={t('common.confirm', { defaultValue: 'Confirm' })}
                    >
                      <Check size={11} />
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingMeasureId(null)}
                      className="inline-flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:bg-surface-tertiary shrink-0"
                      aria-label={t('common.cancel', { defaultValue: 'Cancel' })}
                    >
                      <X size={11} />
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => handleFocusMeasurement(m.id)}
                      className="flex flex-1 min-w-0 items-center gap-1.5 text-left"
                      title={t('bim.tools_measure_focus', { defaultValue: 'Focus camera' })}
                    >
                      <Crosshair size={10} className="text-oe-blue shrink-0" />
                      <span className="truncate text-[11px] text-content-primary">{m.label}</span>
                      <span className="text-[10px] tabular-nums text-content-tertiary shrink-0">
                        {(() => {
                          const d = q.convert(m.distance, 'm');
                          return `${fmtFixed(d.value, 2)} ${d.unit}`;
                        })()}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setEditingMeasureId(m.id);
                        setEditingMeasureDraft(m.label);
                      }}
                      className="inline-flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:bg-surface-tertiary hover:text-oe-blue shrink-0"
                      aria-label={t('bim.tools_measure_rename', {
                        defaultValue: 'Rename measurement',
                      })}
                    >
                      <Pencil size={11} />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleToggleMeasurementVisible(m)}
                      className="inline-flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:bg-surface-tertiary shrink-0"
                      aria-label={
                        m.visible
                          ? t('bim.tools_measure_hide', { defaultValue: 'Hide' })
                          : t('bim.tools_measure_show', { defaultValue: 'Show' })
                      }
                    >
                      {m.visible ? <Eye size={11} /> : <EyeOff size={11} />}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDeleteMeasurement(m.id)}
                      className="inline-flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:bg-surface-tertiary hover:text-rose-600 shrink-0"
                      aria-label={t('bim.tools_measure_delete', {
                        defaultValue: 'Delete measurement',
                      })}
                      data-testid="measurement-delete"
                    >
                      <Trash2 size={11} />
                    </button>
                  </>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      {/* Saved views */}
      <section className="flex flex-col gap-2">
        <h3 className="text-xs font-semibold text-content-primary uppercase tracking-wide">
          {t('bim.tools_views_title', { defaultValue: 'Saved views' })}
        </h3>
        {/* Tightened layout (RFC 19 §UX-5):
            – `min-w-0` on the input lets it actually shrink so the Save
              button never gets pushed past the panel's right edge.
            – `shrink-0` on the button locks its width.
            – `gap-1.5` keeps the spacing snug enough that 320px panels fit. */}
        <div className="flex items-center gap-1.5 min-w-0">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('bim.tools_view_name_placeholder', {
              defaultValue: 'View name…',
            })}
            className="min-w-0 flex-1 rounded-md border border-border-light bg-surface-primary px-2 py-1 text-[11px] text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
            data-testid="save-view-name"
          />
          <button
            type="button"
            onClick={handleSave}
            className="shrink-0 inline-flex items-center gap-1 rounded-md bg-oe-blue px-2 py-1 text-[11px] font-medium text-white hover:bg-oe-blue-dark"
            data-testid="save-view-button"
          >
            <Camera size={12} />
            {t('bim.tools_views_save', { defaultValue: 'Save' })}
          </button>
        </div>
        {/* Thumbnail toggle - small inline checkbox so the user can opt out
            of the ~50 KB PNG attachment when bookmarking a hundred angles. */}
        <label className="flex items-center gap-1.5 text-[10px] text-content-tertiary select-none cursor-pointer">
          <input
            type="checkbox"
            checked={includeScreenshot}
            onChange={(e) => setIncludeScreenshot(e.target.checked)}
            className="h-3 w-3"
            data-testid="save-view-include-screenshot"
          />
          <ImageIcon size={10} />
          {t('bim.tools_views_attach_thumb', {
            defaultValue: 'Attach thumbnail (PNG, ~50 KB)',
          })}
        </label>
        {quotaWarning && (
          <div
            role="alert"
            className="rounded-md border border-amber-300 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-800 px-2 py-1 text-[10px] text-amber-700 dark:text-amber-200"
          >
            {t('bim.tools_views_quota', {
              defaultValue:
                'Limit of 100 views per model reached - the oldest was removed.',
            })}
          </div>
        )}
        <ul className="flex flex-col gap-1" data-testid="saved-views-list">
          {views.length === 0 && (
            <li className="text-[11px] text-content-tertiary italic">
              {t('bim.tools_views_empty', {
                defaultValue: 'No saved views yet.',
              })}
            </li>
          )}
          {views.map((v) => {
            const isEditing = editingViewId === v.id;
            return (
              <li
                key={v.id}
                className="flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-2 py-1 min-w-0"
                data-testid="saved-view-row"
              >
                {isEditing ? (
                  <>
                    <input
                      type="text"
                      value={editingViewDraft}
                      onChange={(e) => setEditingViewDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleConfirmRename();
                        if (e.key === 'Escape') handleCancelRename();
                      }}
                      autoFocus
                      className="flex-1 min-w-0 rounded border border-border-light bg-surface-secondary px-1 py-0.5 text-[11px]"
                      data-testid="rename-view-input"
                    />
                    <button
                      type="button"
                      onClick={handleConfirmRename}
                      className="inline-flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:bg-surface-tertiary hover:text-emerald-600 shrink-0"
                      aria-label={t('common.confirm', { defaultValue: 'Confirm' })}
                    >
                      <Check size={11} />
                    </button>
                    <button
                      type="button"
                      onClick={handleCancelRename}
                      className="inline-flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:bg-surface-tertiary shrink-0"
                      aria-label={t('common.cancel', { defaultValue: 'Cancel' })}
                    >
                      <X size={11} />
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => onApplyViewpoint(v)}
                      className="flex flex-1 min-w-0 items-center gap-2 text-left text-[11px] text-content-primary hover:text-oe-blue"
                      data-testid={`apply-view-${v.name}`}
                      title={new Date(v.createdAt).toLocaleString(getIntlLocale())}
                    >
                      {v.screenshotDataUrl ? (
                        // Thumbnail preview - keeps the row to ~24px tall by
                        // forcing a 32×20 aspect window. Image alt is the
                        // view name so screen readers still announce the row.
                        <img
                          src={v.screenshotDataUrl}
                          alt={v.name}
                          className="w-8 h-5 rounded object-cover border border-border-light shrink-0"
                          data-testid="saved-view-thumb"
                        />
                      ) : (
                        <Play size={10} className="shrink-0" />
                      )}
                      <span className="truncate">{v.name}</span>
                      {/* Tiny badges hint at what the view captured. */}
                      {v.clipState && v.clipState.mode !== 'none' && (
                        <span
                          className="ms-1 shrink-0 rounded bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 px-1 py-px text-[8px] font-semibold uppercase"
                          title={t('bim.tools_views_has_clip', {
                            defaultValue: 'Has section clip',
                          })}
                        >
                          {v.clipState.mode}
                        </span>
                      )}
                      {v.filterState && (
                        (v.filterState.storeys?.length ?? 0) > 0 ||
                        (v.filterState.types?.length ?? 0) > 0 ||
                        !!v.filterState.search
                      ) && (
                        <span
                          className="ms-1 shrink-0 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 px-1 py-px text-[8px] font-semibold uppercase"
                          title={t('bim.tools_views_has_filter', {
                            defaultValue: 'Has filter',
                          })}
                        >
                          {t('bim.tools_views_filter_badge', { defaultValue: 'flt' })}
                        </span>
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleStartRename(v)}
                      aria-label={t('bim.tools_views_rename', {
                        defaultValue: 'Rename view {{name}}',
                        name: v.name,
                      })}
                      className="inline-flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:bg-surface-tertiary hover:text-oe-blue shrink-0"
                      data-testid="rename-view-button"
                    >
                      <Pencil size={11} />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleRemove(v.id)}
                      aria-label={t('bim.tools_views_delete', {
                        defaultValue: 'Delete view {{name}}',
                        name: v.name,
                      })}
                      className="inline-flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:bg-surface-tertiary hover:text-rose-600 shrink-0"
                    >
                      <Trash2 size={11} />
                    </button>
                  </>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      {/* Export - IFC/RVT quantities to a single Excel Bill of Quantities */}
      <section className="flex flex-col gap-2">
        <h3 className="text-xs font-semibold text-content-primary uppercase tracking-wide">
          {t('bim.tools_export_title', { defaultValue: 'Export' })}
        </h3>
        <p className="text-[10px] text-content-tertiary">
          {t('bim.boq_export_hint', {
            defaultValue:
              'Roll the model quantities (area, volume, length, weight) into one Excel Bill of Quantities.',
          })}
        </p>
        <label className="flex flex-col gap-1 text-[10px] text-content-tertiary">
          {t('bim.boq_export_scope', { defaultValue: 'Elements' })}
          <select
            value={exportScope}
            onChange={(e) => setExportScope(e.target.value as BoqExportScope)}
            data-testid="boq-export-scope"
            className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-[11px] text-content-primary"
          >
            <option value="all">{t('bim.boq_export_scope_all', { defaultValue: 'Whole model' })}</option>
            <option value="filter">
              {t('bim.boq_export_scope_filter', { defaultValue: 'Current filter' })}
            </option>
            <option value="selected">
              {t('bim.boq_export_scope_selected', { defaultValue: 'Selected only' })}
            </option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[10px] text-content-tertiary">
          {t('bim.boq_export_group_by', { defaultValue: 'Group by' })}
          <select
            value={exportGroupBy}
            onChange={(e) => setExportGroupBy(e.target.value as BoqGroupBy)}
            data-testid="boq-export-group-by"
            className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-[11px] text-content-primary"
          >
            <option value="element_type">
              {t('bim.boq_export_by_type', { defaultValue: 'Element type' })}
            </option>
            <option value="storey">{t('bim.boq_export_by_storey', { defaultValue: 'Storey' })}</option>
            <option value="discipline">
              {t('bim.boq_export_by_discipline', { defaultValue: 'Discipline' })}
            </option>
            <option value="element_type_storey">
              {t('bim.boq_export_by_type_storey', { defaultValue: 'Type and storey' })}
            </option>
          </select>
        </label>
        <button
          type="button"
          onClick={handleExportBoq}
          disabled={exporting}
          data-testid="boq-export-button"
          className="flex items-center justify-center gap-2 px-3 py-1.5 rounded-md text-[11px] font-medium bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-60"
        >
          <FileSpreadsheet size={12} />
          {exporting
            ? t('bim.boq_export_running', { defaultValue: 'Exporting…' })
            : t('bim.boq_export_button', { defaultValue: 'Export BOQ (Excel)' })}
        </button>
        {onOpenReport && (
          <button
            type="button"
            onClick={() => onOpenReport(exportScope, exportGroupBy)}
            data-testid="boq-report-button"
            className="flex items-center justify-center gap-2 px-3 py-1.5 rounded-md text-[11px] font-medium border border-border-light bg-surface-secondary text-content-secondary hover:bg-surface-tertiary"
          >
            <FileBarChart size={12} />
            {t('bim.boq_report_button', { defaultValue: 'View summary report' })}
          </button>
        )}
      </section>
    </div>
  );
}
