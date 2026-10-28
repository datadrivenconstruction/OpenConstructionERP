// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ColorByPropertyPanel — right-rail panel that lets the user re-colour BIM
 * elements by an arbitrary property and pick from a small set of palettes
 * (categorical, sequential, diverging, or a domain-specific fire-rating
 * lookup).  The legend below the controls stays in lock-step with the live
 * colouring so users can read what each swatch means.
 *
 * Owned by W6.6 ("BIM Viewer Pro UX").  Integrator follow-up: wire this
 * panel into the right-rail tab strip in `BIMRightPanelTabs.tsx` so it
 * surfaces alongside Layers / Tools / Groups.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Palette as PaletteIcon, RotateCcw } from 'lucide-react';
import {
  CATEGORICAL_12,
  FIRE_RATING_PALETTE,
  colorForPropertyValue,
  type ColorByPropertyConfig,
  type ColorByPropertyPalette,
  type ElementManager,
  type PropertyValueCount,
} from '@/shared/ui/BIMViewer';

interface ColorByPropertyPanelProps {
  /** Live ElementManager handle; `null` while the viewer is mounting. */
  elementManager: ElementManager | null;
  className?: string;
}

const PALETTES: { value: ColorByPropertyPalette; labelKey: string; defaultLabel: string }[] = [
  { value: 'categorical-12', labelKey: 'bim.color_palette_categorical', defaultLabel: 'Categorical (12 colors)' },
  { value: 'sequential-blue', labelKey: 'bim.color_palette_seq_blue', defaultLabel: 'Sequential - blue' },
  { value: 'sequential-red-blue', labelKey: 'bim.color_palette_diverging', defaultLabel: 'Diverging - red ⇄ blue' },
  { value: 'fire-rating', labelKey: 'bim.color_palette_fire_rating', defaultLabel: 'Fire rating (F30 / F60 / F90)' },
];

/** True when this palette needs numeric min/max inputs. */
function paletteIsNumeric(p: ColorByPropertyPalette): boolean {
  return p === 'sequential-blue' || p === 'sequential-red-blue';
}

/**
 * Compute a default numeric range from the distinct values list.  Falls
 * back to [0, 1] when no value is numeric (the user can still type their
 * own range — the picker just needs sensible defaults).
 */
function computeNumericRange(distinct: PropertyValueCount[]): [number, number] {
  let min = Infinity;
  let max = -Infinity;
  for (const { value } of distinct) {
    const n = typeof value === 'number' ? value : Number(value);
    if (Number.isFinite(n)) {
      if (n < min) min = n;
      if (n > max) max = n;
    }
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  if (min === max) return [min, min + 1];
  return [min, max];
}

export default function ColorByPropertyPanel({
  elementManager,
  className,
}: ColorByPropertyPanelProps) {
  const { t } = useTranslation();

  const [propertyKey, setPropertyKey] = useState<string>('');
  const [palette, setPalette] = useState<ColorByPropertyPalette>('categorical-12');
  const [rangeMin, setRangeMin] = useState<string>('0');
  const [rangeMax, setRangeMax] = useState<string>('1');

  // Pull the available keys + distinct values straight from the manager.
  // We recompute on every render — the cost is O(elements) and the panel
  // re-renders only when the user opens it or toggles a control.
  const availableKeys = useMemo(
    () => (elementManager ? elementManager.getAvailablePropertyKeys() : []),
    [elementManager],
  );

  const distinct = useMemo<PropertyValueCount[]>(
    () =>
      elementManager && propertyKey
        ? elementManager.getDistinctPropertyValues(propertyKey)
        : [],
    [elementManager, propertyKey],
  );

  // When the property changes and the palette is numeric, auto-fill the
  // range from the value extremes so the user gets a sensible starting
  // gradient.
  useEffect(() => {
    if (!paletteIsNumeric(palette)) return;
    const [lo, hi] = computeNumericRange(distinct);
    setRangeMin(String(lo));
    setRangeMax(String(hi));
  }, [palette, distinct]);

  // Default the property key to the first available so the panel renders
  // a useful state on first open (rather than the empty dropdown).
  useEffect(() => {
    if (propertyKey === '' && availableKeys.length > 0) {
      setPropertyKey(availableKeys[0]!);
    }
  }, [availableKeys, propertyKey]);

  const numericRange: [number, number] = useMemo(() => {
    const lo = Number(rangeMin);
    const hi = Number(rangeMax);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 1];
    return [lo, hi];
  }, [rangeMin, rangeMax]);

  const handleApply = () => {
    if (!elementManager || !propertyKey) return;
    const config: ColorByPropertyConfig = {
      propertyKey,
      palette,
      ...(paletteIsNumeric(palette) ? { numericRange } : {}),
    };
    elementManager.setColorByProperty(config);
  };

  const handleReset = () => {
    if (!elementManager) return;
    elementManager.setColorByProperty(null);
  };

  const previewConfig: ColorByPropertyConfig = useMemo(
    () => ({
      propertyKey,
      palette,
      ...(paletteIsNumeric(palette) ? { numericRange } : {}),
    }),
    [propertyKey, palette, numericRange],
  );

  const showRangeInputs = paletteIsNumeric(palette);
  const disabled = !elementManager || !propertyKey;

  return (
    <div
      data-testid="bim-color-by-property-panel"
      className={`flex flex-col gap-3 p-3 ${className ?? ''}`}
    >
      <div className="flex items-center gap-2">
        <PaletteIcon size={14} className="text-content-tertiary" />
        <h3 className="text-xs font-semibold text-content-primary uppercase tracking-wide">
          {t('bim.color_by_property_title', {
            defaultValue: 'Color by property',
          })}
        </h3>
      </div>

      {/* Property picker */}
      <label className="flex flex-col gap-1 text-[11px] text-content-secondary">
        <span>
          {t('bim.color_property_label', { defaultValue: 'Property' })}
        </span>
        <select
          value={propertyKey}
          onChange={(e) => setPropertyKey(e.target.value)}
          data-testid="bim-color-by-property-key"
          className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
        >
          {availableKeys.length === 0 ? (
            <option value="">
              {t('bim.color_no_properties', { defaultValue: 'No properties available' })}
            </option>
          ) : (
            availableKeys.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))
          )}
        </select>
      </label>

      {/* Palette picker */}
      <label className="flex flex-col gap-1 text-[11px] text-content-secondary">
        <span>
          {t('bim.color_palette_label', { defaultValue: 'Palette' })}
        </span>
        <select
          value={palette}
          onChange={(e) => setPalette(e.target.value as ColorByPropertyPalette)}
          data-testid="bim-color-by-property-palette"
          className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
        >
          {PALETTES.map((p) => (
            <option key={p.value} value={p.value}>
              {t(p.labelKey, { defaultValue: p.defaultLabel })}
            </option>
          ))}
        </select>
      </label>

      {/* Numeric range inputs for sequential palettes */}
      {showRangeInputs && (
        <div className="flex items-end gap-2">
          <label className="flex flex-1 flex-col gap-1 text-[11px] text-content-secondary">
            <span>{t('bim.color_range_min', { defaultValue: 'Min' })}</span>
            <input
              type="number"
              value={rangeMin}
              onChange={(e) => setRangeMin(e.target.value)}
              data-testid="bim-color-by-property-min"
              className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
            />
          </label>
          <label className="flex flex-1 flex-col gap-1 text-[11px] text-content-secondary">
            <span>{t('bim.color_range_max', { defaultValue: 'Max' })}</span>
            <input
              type="number"
              value={rangeMax}
              onChange={(e) => setRangeMax(e.target.value)}
              data-testid="bim-color-by-property-max"
              className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
            />
          </label>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleApply}
          disabled={disabled}
          data-testid="bim-color-by-property-apply"
          className="flex-1 rounded-md bg-oe-blue px-3 py-1.5 text-xs font-medium text-white hover:bg-oe-blue/90 disabled:opacity-40 disabled:pointer-events-none"
        >
          {t('bim.color_apply', { defaultValue: 'Apply' })}
        </button>
        <button
          type="button"
          onClick={handleReset}
          data-testid="bim-color-by-property-reset"
          className="flex items-center gap-1 rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-xs text-content-secondary hover:bg-surface-secondary"
        >
          <RotateCcw size={12} />
          {t('bim.color_reset', { defaultValue: 'Reset' })}
        </button>
      </div>

      {/* Legend */}
      <div className="flex flex-col gap-1">
        <div className="text-[10px] font-semibold uppercase tracking-wide text-content-tertiary">
          {t('bim.color_legend', { defaultValue: 'Legend' })}
        </div>
        {palette === 'categorical-12' || palette === 'fire-rating' ? (
          <CategoricalLegend
            distinct={distinct}
            config={previewConfig}
          />
        ) : (
          <GradientLegend
            config={previewConfig}
          />
        )}
      </div>
    </div>
  );
}

/* ── Sub-components ─────────────────────────────────────────────────────── */

function CategoricalLegend({
  distinct,
  config,
}: {
  distinct: PropertyValueCount[];
  config: ColorByPropertyConfig;
}) {
  // For fire-rating we always render the canonical lookup so users see the
  // full palette even when the model only has a subset. For categorical-12
  // we list the top-12 most-common values.
  if (config.palette === 'fire-rating') {
    const rows = Object.keys(FIRE_RATING_PALETTE).map((key) => ({
      value: key.toUpperCase(),
      count: distinct.find((d) => String(d.value).toLowerCase() === key)?.count ?? 0,
      color: FIRE_RATING_PALETTE[key]!,
    }));
    return (
      <ul className="flex flex-col gap-0.5">
        {rows.map((r) => (
          <li
            key={r.value}
            className="flex items-center gap-2 text-[11px] text-content-secondary"
          >
            <span
              className="inline-block h-3 w-3 rounded-sm border border-border-light"
              style={{ backgroundColor: r.color }}
              aria-hidden="true"
            />
            <span className="flex-1 truncate">{r.value}</span>
            <span className="tabular-nums text-content-tertiary">{r.count}</span>
          </li>
        ))}
      </ul>
    );
  }

  const top = distinct.slice(0, CATEGORICAL_12.length);
  return (
    <ul className="flex flex-col gap-0.5">
      {top.length === 0 ? (
        <li className="text-[11px] text-content-tertiary italic">—</li>
      ) : (
        top.map((row, i) => (
          <li
            key={String(row.value)}
            className="flex items-center gap-2 text-[11px] text-content-secondary"
          >
            <span
              className="inline-block h-3 w-3 rounded-sm border border-border-light"
              style={{ backgroundColor: colorForPropertyValue(config, row.value, i) }}
              aria-hidden="true"
            />
            <span className="flex-1 truncate" title={String(row.value)}>
              {String(row.value)}
            </span>
            <span className="tabular-nums text-content-tertiary">{row.count}</span>
          </li>
        ))
      )}
    </ul>
  );
}

function GradientLegend({ config }: { config: ColorByPropertyConfig }) {
  // 10-tick gradient bar so users see the full scale at a glance.
  const ticks = 10;
  const [lo, hi] = config.numericRange ?? [0, 1];
  const segments = useMemo(() => {
    const arr: { color: string; t: number }[] = [];
    for (let i = 0; i < ticks; i++) {
      const t = i / (ticks - 1);
      const value = lo + (hi - lo) * t;
      arr.push({
        color: colorForPropertyValue(config, value, i),
        t,
      });
    }
    return arr;
  }, [config, lo, hi]);

  return (
    <div className="flex flex-col gap-1">
      <div className="flex h-3 w-full overflow-hidden rounded-sm border border-border-light">
        {segments.map((s, i) => (
          <span
            key={i}
            className="flex-1"
            style={{ backgroundColor: s.color }}
            aria-hidden="true"
          />
        ))}
      </div>
      <div className="flex justify-between text-[10px] tabular-nums text-content-tertiary">
        <span>{lo}</span>
        <span>{hi}</span>
      </div>
    </div>
  );
}
