// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Two-click scale calibration dialog.
 *
 * Called with the measured pixel distance between the two points the
 * user clicked on the PDF.  The user enters a real-world length and
 * picks one of four units (m, mm, ft, in).  On confirm, we convert the
 * value to meters and ask the parent to persist the new `ScaleConfig`
 * via `deriveScale()`.
 *
 * Keyboard:
 *   - Enter confirms (if the input is valid)
 *   - Esc cancels (handled by WideModal)
 */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Ruler } from 'lucide-react';
import {
  type CalibrationUnit,
  deriveScale,
  toMeters,
  type ScaleConfig,
} from '../../../modules/pdf-takeoff/data/scale-helpers';
import { WideModal } from '@/shared/ui/WideModal';
import { Button } from '@/shared/ui';
import { formatFixedDigits, formatMaxDigits } from '../lib/measurement-format';
import { fmtFixed } from '@/shared/lib/formatters';

/** What the user actually typed, for honest badge display.
 *
 *  The derived {@link ScaleConfig} is intentionally **metric-canonical**
 *  (`pixelsPerUnit` is always px-per-metre, `unitLabel` is always `'m'`),
 *  because every downstream consumer — preset scales, `ratioFromScale`,
 *  the recalc effect — assumes metres (see scale-helpers `deriveScale`).
 *  An estimator who calibrated in feet would otherwise see a bare `'m'`
 *  with no hint their feet were honoured (D-TKC-016).  We surface the
 *  raw entry so the calibration badge can show `10 ft → 3.05 m`. */
export interface CalibrationEntry {
  /** The number the user typed. */
  realLength: number;
  /** The unit the user picked in the dialog. */
  unit: CalibrationUnit;
}

export interface CalibrationDialogProps {
  /** Measured pixel distance between the two picked points. */
  pixelDistance: number;
  /** Called when the user confirms a valid calibration.  The second
   *  argument echoes the user's raw entry (value + chosen unit) so the
   *  caller can label the calibration in the unit the estimator actually
   *  used, even though `scale` itself stays metric-canonical. */
  onConfirm: (scale: ScaleConfig, entry: CalibrationEntry) => void;
  /** Called when the user cancels (Esc, backdrop click, Cancel button). */
  onCancel: () => void;
  /** Optional initial real-length value (defaults to 1). */
  initialRealLength?: number;
  /** Optional initial unit (defaults to meters). */
  initialUnit?: CalibrationUnit;
}

// Labels resolve through i18n inside the component (the dialog is otherwise
// fully localised; hardcoded English words here leaked into every locale).
const UNIT_OPTIONS: { value: CalibrationUnit; labelKey: string; labelDefault: string }[] = [
  { value: 'm', labelKey: 'takeoff_viewer.calibrate_unit_m', labelDefault: 'm (meters)' },
  { value: 'mm', labelKey: 'takeoff_viewer.calibrate_unit_mm', labelDefault: 'mm (millimeters)' },
  { value: 'ft', labelKey: 'takeoff_viewer.calibrate_unit_ft', labelDefault: 'ft (feet)' },
  { value: 'in', labelKey: 'takeoff_viewer.calibrate_unit_in', labelDefault: 'in (inches)' },
];

export function CalibrationDialog({
  pixelDistance,
  onConfirm,
  onCancel,
  initialRealLength = 1,
  initialUnit = 'm',
}: CalibrationDialogProps) {
  const { t } = useTranslation();
  const [realLength, setRealLength] = useState<string>(String(initialRealLength));
  const [unit, setUnit] = useState<CalibrationUnit>(initialUnit);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.select();
  }, []);

  const parsed = Number(realLength);
  const isValid = Number.isFinite(parsed) && parsed > 0 && pixelDistance > 0;

  const handleConfirm = () => {
    if (!isValid) return;
    const meters = toMeters(parsed, unit);
    // `scale` stays metric-canonical (deriveScale always labels in metres
    // — every downstream consumer assumes that).  We additionally hand the
    // caller the raw entry so the calibration badge can honour the unit
    // the estimator actually typed (D-TKC-016).
    onConfirm(deriveScale(pixelDistance, meters), { realLength: parsed, unit });
  };

  return (
    <WideModal
      open
      onClose={onCancel}
      title={t('takeoff_viewer.calibrate_title', { defaultValue: 'Calibrate Scale' })}
      size="sm"
      subtitle={
        <span className="inline-flex items-center gap-1.5">
          <Ruler size={12} className="text-purple-500" />
          {t('takeoff_viewer.calibrate_desc', {
            defaultValue:
              'You picked a line of {{pixels}} pixels. Enter its real-world length:',
            pixels: fmtFixed(pixelDistance, 0),
          })}
        </span>
      }
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={handleConfirm}
            disabled={!isValid}
            data-testid="calibration-confirm"
          >
            {t('takeoff_viewer.calibrate_confirm', {
              defaultValue: 'Apply calibration',
            })}
          </Button>
        </>
      }
    >
      <div data-testid="calibration-dialog">
        <div className="grid grid-cols-[1fr_auto] gap-2 mb-4">
          <input
            ref={inputRef}
            type="number"
            value={realLength}
            onChange={(e) => setRealLength(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && isValid) handleConfirm();
            }}
            className="rounded border border-border bg-surface-secondary px-2 py-1.5 text-sm text-content-primary"
            min={0}
            step={0.01}
            aria-label={t('takeoff_viewer.calibrate_length', {
              defaultValue: 'Real-world length',
            })}
            data-testid="calibration-length-input"
          />
          <select
            value={unit}
            onChange={(e) => setUnit(e.target.value as CalibrationUnit)}
            className="rounded border border-border bg-surface-secondary px-2 py-1.5 text-sm text-content-primary"
            aria-label={t('takeoff_viewer.calibrate_unit', { defaultValue: 'Unit' })}
            data-testid="calibration-unit-select"
          >
            {UNIT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {t(opt.labelKey, { defaultValue: opt.labelDefault })}
              </option>
            ))}
          </select>
        </div>
        {isValid && unit !== 'm' && (
          <p
            className="text-[10px] text-purple-500/90 mb-2 tabular-nums"
            data-testid="calibration-metric-note"
          >
            {t('takeoff_viewer.calibrate_metric_note', {
              defaultValue:
                '{{value}} {{unit}} = {{meters}} m - measurements display in metres (metric-canonical).',
              // Both sides of the equation carry locale digits: a raw
              // "12000 mm" next to a grouped "12,000 m" reads as two
              // different numbers in German.
              value: formatMaxDigits(parsed, 3),
              unit,
              meters: formatFixedDigits(toMeters(parsed, unit), 3),
            })}
          </p>
        )}
        <p className="text-[10px] text-content-tertiary">
          {t('takeoff_viewer.calibrate_hint', {
            defaultValue:
              'Tip: pick two points along a known dimension (door, wall, grid line).',
          })}
        </p>
      </div>
    </WideModal>
  );
}

export default CalibrationDialog;
