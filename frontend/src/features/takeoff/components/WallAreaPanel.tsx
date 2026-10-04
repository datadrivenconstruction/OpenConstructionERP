// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Wall area panel for a linear takeoff measurement (distance / polyline).
 *
 * A wall is drawn on the plan as a line. Typing its height turns the reported
 * quantity from a length into a wall area (length x height), and openings
 * (doors, windows) typed as width x height x count are deducted from it. The
 * panel shows the whole sum live, "12.50 m x 2.80 m = 35.00 m²", so the
 * estimator can check the figure that lands in the bill at a glance.
 *
 * Inputs are in the reader's measurement system (metres or decimal feet) and
 * stored in canonical metres; the math lives in `takeoff-quantity.ts` and the
 * input conversion in `takeoff-wall.ts`.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Plus, Trash2 } from 'lucide-react';
import type { MeasurementSystem } from '@/stores/usePreferencesStore';
import { localizedUnitCode } from '@/shared/lib/unitLabels';
import type { Measurement, WallOpening } from '../lib/takeoff-types';
import { formatMaxDigits, formatQuantity } from '../lib/measurement-format';
import { convertQuantity } from '../lib/takeoff-display-units';
import { effectiveUnit, isWallMeasurement, openingArea, openingsExceedGross } from '../lib/takeoff-quantity';
import {
  addOpening,
  lengthToInput,
  openingsForStore,
  parseCountInput,
  parseLengthInput,
  removeOpening,
  wallBreakdown,
} from '../lib/takeoff-wall';

export interface WallAreaPanelProps {
  measurement: Measurement;
  measurementSystem: MeasurementSystem;
  onChange: (patch: { wallHeight?: number; openings?: WallOpening[] }) => void;
}

export function WallAreaPanel({ measurement, measurementSystem, onChange }: WallAreaPanelProps) {
  const { t, i18n } = useTranslation();
  const system = measurementSystem;
  const lengthUnitLabel = localizedUnitCode(
    convertQuantity(0, measurement.unit || 'm', system).unit,
    i18n.language,
  );

  // Draft text for the height box. Re-seeded only when the selection or the
  // unit system changes, so typing "2," is not normalised mid-keystroke.
  const [heightDraft, setHeightDraft] = useState(() => lengthToInput(measurement.wallHeight, system));
  useEffect(() => {
    setHeightDraft(lengthToInput(measurement.wallHeight, system));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [measurement.id, system]);

  const [openingDraft, setOpeningDraft] = useState({ width: '', height: '', count: '1' });
  useEffect(() => {
    setOpeningDraft({ width: '', height: '', count: '1' });
  }, [measurement.id]);

  const isWall = isWallMeasurement(measurement);
  // Unit the stored opening areas are in (the length unit squared, m²).
  const storedAreaUnit = effectiveUnit({ type: 'distance', unit: measurement.unit || 'm', wallHeight: 1 });
  const fmt = (v: number) => formatQuantity(v);
  const unit = (u: string) => localizedUnitCode(u, i18n.language);

  const draftWidth = parseLengthInput(openingDraft.width, system);
  const draftHeight = parseLengthInput(openingDraft.height, system);
  const draftCount = parseCountInput(openingDraft.count);
  const canAddOpening = draftWidth !== null && draftHeight !== null && draftCount !== null;

  const handleAddOpening = () => {
    if (!canAddOpening) return;
    onChange({
      openings: addOpening(measurement.openings, {
        width: draftWidth!,
        height: draftHeight!,
        count: draftCount!,
      }),
    });
    setOpeningDraft({ width: '', height: '', count: '1' });
  };

  const breakdown = isWall ? wallBreakdown(measurement, system) : null;
  const openings = isWall ? measurement.openings ?? [] : [];

  return (
    <div
      className="space-y-1.5 rounded border border-border/60 bg-surface-secondary/30 p-2"
      data-testid="wall-area-panel"
    >
      <label className="text-[10px] font-semibold text-content-tertiary flex items-center justify-between">
        <span>{t('takeoff_wall.height', { defaultValue: 'Wall height' })}</span>
        {measurement.wallHeight != null && (
          <button
            type="button"
            onClick={() => {
              setHeightDraft('');
              onChange({ wallHeight: undefined });
            }}
            className="text-[10px] text-content-tertiary hover:text-content-primary underline"
            data-testid="wall-height-reset"
          >
            {t('takeoff_viewer.reset', { defaultValue: 'Reset' })}
          </button>
        )}
      </label>
      <div className="flex items-center gap-1.5">
        <input
          type="text"
          inputMode="decimal"
          value={heightDraft}
          placeholder={formatMaxDigits(system === 'imperial' ? 9 : 2.8, 2)}
          onChange={(e) => {
            const text = e.target.value;
            setHeightDraft(text);
            const metres = parseLengthInput(text, system);
            if (metres !== null) onChange({ wallHeight: metres });
            else if (!text.trim()) onChange({ wallHeight: undefined });
          }}
          aria-label={t('takeoff_wall.height', { defaultValue: 'Wall height' })}
          className="w-24 rounded border border-border bg-surface-primary px-2 py-1 text-xs text-content-primary tabular-nums"
          data-testid="wall-height-input"
        />
        <span className="text-[10px] text-content-tertiary">{lengthUnitLabel}</span>
      </div>

      {!breakdown ? (
        <p className="text-[10px] text-content-tertiary" data-testid="wall-height-hint">
          {t('takeoff_wall.height_hint', {
            defaultValue: 'Enter the wall height to report wall area (length x height) instead of length.',
          })}
        </p>
      ) : (
        <>
          <p
            className="font-mono tabular-nums text-[11px] text-content-primary"
            data-testid="wall-area-formula"
          >
            {`${fmt(breakdown.length)} ${unit(breakdown.lengthUnit)} × ${fmt(breakdown.height)} ${unit(
              breakdown.lengthUnit,
            )} = ${fmt(breakdown.gross)} ${unit(breakdown.areaUnit)}`}
          </p>

          <p className="text-[10px] font-semibold text-content-tertiary pt-1">
            {t('takeoff_wall.openings', { defaultValue: 'Openings (doors, windows)' })}
          </p>
          {openings.length > 0 && (
            <ul className="space-y-0.5" data-testid="wall-openings-list">
              {openings.map((o, idx) => {
                const area = convertQuantity(openingArea(o), storedAreaUnit, system);
                const w = convertQuantity(o.width, measurement.unit || 'm', system);
                const h = convertQuantity(o.height, measurement.unit || 'm', system);
                return (
                  <li
                    key={idx}
                    className="flex items-center gap-1.5 text-[10px] font-mono tabular-nums text-content-secondary"
                    data-testid="wall-opening-row"
                  >
                    <span className="flex-1">
                      {`${o.count} × ${fmt(w.value)} × ${fmt(h.value)} ${unit(w.unit)} = −${fmt(area.value)} ${unit(
                        area.unit,
                      )}`}
                    </span>
                    <button
                      type="button"
                      onClick={() => onChange({ openings: openingsForStore(removeOpening(measurement.openings, idx)) })}
                      className="text-content-tertiary hover:text-semantic-error"
                      aria-label={t('takeoff_wall.remove_opening', { defaultValue: 'Remove opening' })}
                      title={t('takeoff_wall.remove_opening', { defaultValue: 'Remove opening' })}
                      data-testid="wall-opening-remove"
                    >
                      <Trash2 size={11} />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto_3rem_auto] items-center gap-1">
            <input
              type="text"
              inputMode="decimal"
              value={openingDraft.width}
              onChange={(e) => setOpeningDraft((d) => ({ ...d, width: e.target.value }))}
              placeholder={t('takeoff_wall.opening_width', { defaultValue: 'Width' })}
              aria-label={t('takeoff_wall.opening_width', { defaultValue: 'Width' })}
              title={t('takeoff_wall.opening_width', { defaultValue: 'Width' })}
              className="min-w-0 rounded border border-border bg-surface-primary px-1.5 py-0.5 text-[11px] tabular-nums"
              data-testid="wall-opening-width"
            />
            <span className="text-[10px] text-content-tertiary">×</span>
            <input
              type="text"
              inputMode="decimal"
              value={openingDraft.height}
              onChange={(e) => setOpeningDraft((d) => ({ ...d, height: e.target.value }))}
              placeholder={t('takeoff_wall.opening_height', { defaultValue: 'Height' })}
              aria-label={t('takeoff_wall.opening_height', { defaultValue: 'Height' })}
              title={t('takeoff_wall.opening_height', { defaultValue: 'Height' })}
              className="min-w-0 rounded border border-border bg-surface-primary px-1.5 py-0.5 text-[11px] tabular-nums"
              data-testid="wall-opening-height"
            />
            <span className="text-[10px] text-content-tertiary">{lengthUnitLabel} ×</span>
            <input
              type="text"
              inputMode="numeric"
              value={openingDraft.count}
              onChange={(e) => setOpeningDraft((d) => ({ ...d, count: e.target.value }))}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleAddOpening();
              }}
              aria-label={t('takeoff_wall.opening_count', { defaultValue: 'Count' })}
              title={t('takeoff_wall.opening_count', { defaultValue: 'Count' })}
              className="min-w-0 rounded border border-border bg-surface-primary px-1.5 py-0.5 text-[11px] tabular-nums"
              data-testid="wall-opening-count"
            />
            <button
              type="button"
              onClick={handleAddOpening}
              disabled={!canAddOpening}
              className="rounded bg-oe-blue p-1 text-white disabled:opacity-40"
              aria-label={t('takeoff_wall.add_opening', { defaultValue: 'Add opening' })}
              title={t('takeoff_wall.add_opening', { defaultValue: 'Add opening' })}
              data-testid="wall-opening-add"
            >
              <Plus size={11} />
            </button>
          </div>

          {openingsExceedGross(measurement) && (
            <p
              className="flex items-center gap-1 text-[10px] text-semantic-error"
              data-testid="wall-openings-exceed"
            >
              <AlertTriangle size={11} className="shrink-0" />
              {t('takeoff_wall.openings_exceed', {
                defaultValue: 'The openings ({{openings}} {{unit}}) are larger than the wall. The wall reports 0.',
                openings: fmt(breakdown.openings),
                unit: unit(breakdown.areaUnit),
              })}
            </p>
          )}

          <div
            className="flex items-center justify-between border-t border-border/50 pt-1 text-[11px]"
            data-testid="wall-area-net"
          >
            <span className="text-content-tertiary">
              {openings.length > 0
                ? t('takeoff_wall.net_area', {
                    defaultValue: '{{gross}} − {{openings}} openings =',
                    gross: fmt(breakdown.gross),
                    openings: fmt(breakdown.openings),
                  })
                : t('takeoff_wall.wall_area', { defaultValue: 'Wall area' })}
            </span>
            <span className="font-mono tabular-nums font-semibold text-oe-blue">
              {`${fmt(Math.max(0, breakdown.gross - breakdown.openings))} ${unit(breakdown.areaUnit)}`}
            </span>
          </div>
        </>
      )}
    </div>
  );
}
