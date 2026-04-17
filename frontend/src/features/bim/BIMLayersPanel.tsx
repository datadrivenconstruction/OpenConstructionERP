/**
 * BIMLayersPanel — Layers tab of the BIM right panel (RFC 19).
 *
 * Shows every element category with a visibility toggle and an opacity
 * slider. Changes are pushed into the Zustand store `useBIMViewerStore`; the
 * BIMViewer reads them and forwards to ElementManager.setCategoryOpacity.
 */
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff } from 'lucide-react';
import type { BIMElementData } from '@/shared/ui/BIMViewer';
import { useBIMViewerStore } from '@/stores/useBIMViewerStore';

interface BIMLayersPanelProps {
  elements: BIMElementData[];
}

export default function BIMLayersPanel({ elements }: BIMLayersPanelProps) {
  const { t } = useTranslation();
  const categoryOpacity = useBIMViewerStore((s) => s.categoryOpacity);
  const hiddenCategories = useBIMViewerStore((s) => s.hiddenCategories);
  const setCategoryOpacity = useBIMViewerStore((s) => s.setCategoryOpacity);
  const setCategoryHidden = useBIMViewerStore((s) => s.setCategoryHidden);
  const resetCategoryOverrides = useBIMViewerStore((s) => s.resetCategoryOverrides);

  const categoryCounts = useMemo(() => {
    const map = new Map<string, number>();
    for (const el of elements) {
      const k = el.element_type || 'Unknown';
      map.set(k, (map.get(k) ?? 0) + 1);
    }
    return [...map.entries()].sort((a, b) => b[1] - a[1]);
  }, [elements]);

  return (
    <div className="flex flex-col gap-2 p-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-content-primary uppercase tracking-wide">
          {t('bim.layers_title', { defaultValue: 'Layers' })}
        </h3>
        <button
          type="button"
          onClick={resetCategoryOverrides}
          className="text-[11px] text-oe-blue hover:underline"
        >
          {t('bim.layers_reset', { defaultValue: 'Reset' })}
        </button>
      </div>
      <div className="flex flex-col gap-1.5">
        {categoryCounts.map(([category, count]) => {
          const opacity = categoryOpacity[category] ?? 1;
          const hidden = hiddenCategories[category] === true;
          return (
            <div
              key={category}
              className="flex flex-col gap-1 p-2 rounded-md border border-border-light bg-surface-primary"
            >
              <div className="flex items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => setCategoryHidden(category, !hidden)}
                  aria-pressed={!hidden}
                  aria-label={
                    hidden
                      ? t('bim.layers_show_category', {
                          defaultValue: 'Show {{category}}',
                          category,
                        })
                      : t('bim.layers_hide_category', {
                          defaultValue: 'Hide {{category}}',
                          category,
                        })
                  }
                  className="inline-flex h-5 w-5 items-center justify-center rounded text-content-secondary hover:bg-surface-tertiary"
                >
                  {hidden ? <EyeOff size={12} /> : <Eye size={12} />}
                </button>
                <span
                  className="flex-1 text-[11px] font-medium text-content-primary truncate"
                  title={category}
                >
                  {category}
                </span>
                <span className="text-[10px] text-content-tertiary tabular-nums">
                  {count}
                </span>
              </div>
              <div className="flex items-center gap-2 px-1">
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={1}
                  value={Math.round(opacity * 100)}
                  onChange={(e) =>
                    setCategoryOpacity(category, Number(e.target.value) / 100)
                  }
                  aria-label={t('bim.layers_opacity', {
                    defaultValue: '{{category}} opacity',
                    category,
                  })}
                  className="flex-1 accent-oe-blue"
                  data-testid={`layer-opacity-${category}`}
                />
                <span className="text-[10px] text-content-tertiary tabular-nums w-8 text-right">
                  {Math.round(opacity * 100)}%
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
