/**
 * BIMToolsPanel — Tools tab of the BIM right panel (RFC 19).
 *
 * Hosts two tool families:
 *   1. Measure distance — on/off toggle. The active flag is held in
 *      `useBIMViewerStore`, the BIMViewer wires it to the MeasureManager.
 *   2. Saved views / camera bookmarks — backed by SavedViewsStore
 *      (localStorage, 100-viewpoints-per-model cap).
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Ruler, Camera, Trash2, Play } from 'lucide-react';
import {
  listViewpoints,
  removeViewpoint,
  addViewpoint,
  type Viewpoint,
} from '@/shared/ui/BIMViewer';
import { useBIMViewerStore } from '@/stores/useBIMViewerStore';

interface BIMToolsPanelProps {
  modelId: string;
  /** Current camera snapshot — provided by the parent so we don't need a
   *  direct handle on the SceneManager. */
  getCurrentViewpoint: () => {
    position: { x: number; y: number; z: number };
    target: { x: number; y: number; z: number };
  } | null;
  /** Move the camera to a stored viewpoint. */
  onApplyViewpoint: (vp: Viewpoint) => void;
}

export default function BIMToolsPanel({
  modelId,
  getCurrentViewpoint,
  onApplyViewpoint,
}: BIMToolsPanelProps) {
  const { t } = useTranslation();
  const measureActive = useBIMViewerStore((s) => s.measureActive);
  const setMeasureActive = useBIMViewerStore((s) => s.setMeasureActive);

  const [views, setViews] = useState<Viewpoint[]>([]);
  const [name, setName] = useState('');
  const [quotaWarning, setQuotaWarning] = useState(false);

  const refresh = useCallback(() => {
    setViews(listViewpoints(modelId));
  }, [modelId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleSave = useCallback(() => {
    const snapshot = getCurrentViewpoint();
    if (!snapshot) return;
    const fallback = new Date().toLocaleString();
    const result = addViewpoint(modelId, {
      name: (name.trim() || fallback).slice(0, 80),
      cameraPos: [snapshot.position.x, snapshot.position.y, snapshot.position.z],
      target: [snapshot.target.x, snapshot.target.y, snapshot.target.z],
    });
    setQuotaWarning(result.quotaExceeded);
    setName('');
    refresh();
  }, [getCurrentViewpoint, modelId, name, refresh]);

  const handleRemove = useCallback(
    (id: string) => {
      removeViewpoint(modelId, id);
      refresh();
    },
    [modelId, refresh],
  );

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
      </section>

      {/* Saved views */}
      <section className="flex flex-col gap-2">
        <h3 className="text-xs font-semibold text-content-primary uppercase tracking-wide">
          {t('bim.tools_views_title', { defaultValue: 'Saved views' })}
        </h3>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('bim.tools_view_name_placeholder', {
              defaultValue: 'View name…',
            })}
            className="flex-1 rounded-md border border-border-light bg-surface-primary px-2 py-1 text-[11px] text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
            data-testid="save-view-name"
          />
          <button
            type="button"
            onClick={handleSave}
            className="inline-flex items-center gap-1 rounded-md bg-oe-blue px-2 py-1 text-[11px] font-medium text-white hover:bg-oe-blue-dark"
            data-testid="save-view-button"
          >
            <Camera size={12} />
            {t('bim.tools_views_save', { defaultValue: 'Save' })}
          </button>
        </div>
        {quotaWarning && (
          <div
            role="alert"
            className="rounded-md border border-amber-300 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-800 px-2 py-1 text-[10px] text-amber-700 dark:text-amber-200"
          >
            {t('bim.tools_views_quota', {
              defaultValue:
                'Limit of 100 views per model reached — the oldest was removed.',
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
          {views.map((v) => (
            <li
              key={v.id}
              className="flex items-center gap-2 rounded-md border border-border-light bg-surface-primary px-2 py-1"
              data-testid="saved-view-row"
            >
              <button
                type="button"
                onClick={() => onApplyViewpoint(v)}
                className="flex flex-1 items-center gap-2 text-left text-[11px] text-content-primary hover:text-oe-blue"
                data-testid={`apply-view-${v.name}`}
                title={new Date(v.createdAt).toLocaleString()}
              >
                <Play size={10} />
                <span className="truncate">{v.name}</span>
              </button>
              <button
                type="button"
                onClick={() => handleRemove(v.id)}
                aria-label={t('bim.tools_views_delete', {
                  defaultValue: 'Delete view {{name}}',
                  name: v.name,
                })}
                className="inline-flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:bg-surface-tertiary hover:text-rose-600"
              >
                <Trash2 size={11} />
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
