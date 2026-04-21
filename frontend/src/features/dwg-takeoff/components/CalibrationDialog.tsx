/**
 * Three-step calibration modal used by the "Calibrate" (K) tool.
 *
 *   Step 1 — Waiting for point A on the drawing
 *   Step 2 — Waiting for point B on the drawing
 *   Step 3 — Pixel distance (read-only) + real-length input + unit dropdown
 *
 * Steps 1 and 2 render as a compact, non-blocking banner at the top of
 * the viewer — the user needs the drawing visible to click points. Step
 * 3 is a centered modal dialog. Esc cancels from any step; Enter confirms
 * only on step 3 (with a valid length).
 *
 * This component is intentionally presentation-only. The parent
 * (``DwgTakeoffPage``) owns the tool state, the captured points, and
 * the localStorage write — we just render + report back.
 */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X, MousePointer2 } from 'lucide-react';
import {
  CALIBRATION_UNITS,
  pixelDistance,
  type CalibrationUnit,
} from '../lib/calibration';

/** Which step the dialog is currently showing. Driven by the parent
 *  (it knows when a click has landed). Step 0 = not open. */
export type CalibrationStep = 0 | 1 | 2 | 3;

interface Props {
  step: CalibrationStep;
  pointA?: [number, number] | null;
  pointB?: [number, number] | null;
  onConfirm: (realLength: number, unit: CalibrationUnit) => void;
  onCancel: () => void;
}

/** Default unit — metres. Estimators working with imperial drawings
 *  flip the dropdown once; subsequent calibrations on other layouts
 *  in the same session could remember the choice, but we keep the
 *  default static so the behaviour is predictable. */
const DEFAULT_UNIT: CalibrationUnit = 'm';

export function CalibrationDialog({
  step,
  pointA,
  pointB,
  onConfirm,
  onCancel,
}: Props) {
  const { t } = useTranslation();
  const [lengthInput, setLengthInput] = useState<string>('');
  const [unit, setUnit] = useState<CalibrationUnit>(DEFAULT_UNIT);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Focus the length input + reset error when step 3 opens.
  useEffect(() => {
    if (step === 3) {
      setError(null);
      // setTimeout so the modal is already mounted when we grab focus.
      const id = setTimeout(() => inputRef.current?.focus(), 0);
      return () => clearTimeout(id);
    } else {
      setLengthInput('');
    }
  }, [step]);

  // Global keyboard shortcuts: Esc cancels everywhere, Enter confirms on step 3.
  useEffect(() => {
    if (step === 0) return;
    const handler = (e: KeyboardEvent) => {
      // Honour the "don't swallow typing" rule — but only skip bare keys,
      // not our actual Esc/Enter handlers. If the target is our own input
      // we still want Enter to confirm, so we special-case it below.
      if (e.key === 'Escape') {
        e.preventDefault();
        onCancel();
        return;
      }
      if (e.key === 'Enter' && step === 3) {
        // Don't double-fire when focus is in our input — the form's
        // onSubmit handles that case. We only care about Enter while
        // focus is elsewhere (e.g. a unit-dropdown button).
        const target = e.target as HTMLElement | null;
        if (target?.tagName === 'TEXTAREA') return;
        e.preventDefault();
        handleSubmit();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, lengthInput, unit]);

  if (step === 0) return null;

  const handleSubmit = () => {
    const v = parseFloat(lengthInput.replace(',', '.'));
    if (!Number.isFinite(v) || v <= 0) {
      setError(
        t('dwg_takeoff.cal_error_length', {
          defaultValue: 'Enter a positive real-world length.',
        }) as string,
      );
      return;
    }
    if (!pointA || !pointB) {
      setError(
        t('dwg_takeoff.cal_error_missing_points', {
          defaultValue: 'Two points are required for calibration.',
        }) as string,
      );
      return;
    }
    if (pixelDistance(pointA, pointB) <= 0) {
      setError(
        t('dwg_takeoff.cal_error_coincident', {
          defaultValue: 'Points are identical — click two different points.',
        }) as string,
      );
      return;
    }
    onConfirm(v, unit);
  };

  /* ── Banner (step 1 / 2) ────────────────────────────────────────── */
  if (step === 1 || step === 2) {
    const label =
      step === 1
        ? t('dwg_takeoff.cal_step1', {
            defaultValue: 'Click point A on the drawing',
          })
        : t('dwg_takeoff.cal_step2', {
            defaultValue: 'Now click point B',
          });
    return (
      <div
        data-testid="dwg-calibration-banner"
        className="absolute top-3 left-1/2 -translate-x-1/2 z-20 flex items-center gap-3 rounded-full border border-oe-blue/40 bg-white/95 dark:bg-slate-900/95 backdrop-blur-md px-4 py-2 shadow-xl ring-1 ring-oe-blue/20"
      >
        <MousePointer2 size={14} className="text-oe-blue" />
        <span className="text-xs font-medium text-slate-800 dark:text-slate-100">
          {label}
        </span>
        <button
          type="button"
          onClick={onCancel}
          aria-label="Cancel calibration"
          className="ml-1 rounded-full p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800"
        >
          <X size={14} />
        </button>
      </div>
    );
  }

  /* ── Modal (step 3) ─────────────────────────────────────────────── */
  const pixels = pointA && pointB ? pixelDistance(pointA, pointB) : 0;

  return (
    <div
      data-testid="dwg-calibration-dialog"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => {
        // Backdrop click cancels.
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleSubmit();
        }}
        className="w-full max-w-sm rounded-xl border border-border bg-surface shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold text-foreground">
            {t('dwg_takeoff.cal_title', {
              defaultValue: 'Calibrate drawing scale',
            })}
          </h2>
          <button
            type="button"
            onClick={onCancel}
            aria-label="Close"
            className="rounded-md p-1 text-muted-foreground hover:bg-surface-secondary hover:text-foreground"
          >
            <X size={14} />
          </button>
        </div>

        <div className="space-y-3 px-4 py-3">
          <div className="flex items-center justify-between rounded-md bg-surface-secondary px-3 py-2">
            <span className="text-xs text-muted-foreground">
              {t('dwg_takeoff.cal_pixel_distance', {
                defaultValue: 'Pixel distance',
              })}
            </span>
            <span
              data-testid="dwg-calibration-pixel-distance"
              className="font-mono text-xs font-semibold text-foreground"
            >
              {pixels.toFixed(2)} px
            </span>
          </div>

          <label className="block text-xs font-medium text-foreground">
            {t('dwg_takeoff.cal_real_length', {
              defaultValue: 'Real-world length',
            })}
            <div className="mt-1 flex gap-2">
              <input
                ref={inputRef}
                data-testid="dwg-calibration-length"
                type="number"
                step="any"
                min="0"
                value={lengthInput}
                onChange={(e) => {
                  setLengthInput(e.target.value);
                  if (error) setError(null);
                }}
                placeholder="e.g. 5"
                className="flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
              />
              <select
                data-testid="dwg-calibration-unit"
                value={unit}
                onChange={(e) => setUnit(e.target.value as CalibrationUnit)}
                className="rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
              >
                {CALIBRATION_UNITS.map((u) => (
                  <option key={u} value={u}>
                    {u}
                  </option>
                ))}
              </select>
            </div>
          </label>

          {error && (
            <p
              data-testid="dwg-calibration-error"
              className="text-xs text-red-500"
              role="alert"
            >
              {error}
            </p>
          )}

          <p className="text-[11px] text-muted-foreground">
            {t('dwg_takeoff.cal_hint', {
              defaultValue:
                'The scale is saved per drawing + layout in your browser.',
            })}
          </p>
        </div>

        <div className="flex justify-end gap-2 border-t border-border px-4 py-3">
          <button
            type="button"
            onClick={onCancel}
            data-testid="dwg-calibration-cancel"
            className="rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-surface-secondary"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="submit"
            data-testid="dwg-calibration-confirm"
            className="rounded-md bg-oe-blue px-3 py-1.5 text-xs font-semibold text-white hover:bg-oe-blue/90"
          >
            {t('common.confirm', { defaultValue: 'Confirm' })}
          </button>
        </div>
      </form>
    </div>
  );
}
