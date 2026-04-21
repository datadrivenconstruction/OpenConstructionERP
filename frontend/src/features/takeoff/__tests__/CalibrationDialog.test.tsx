/**
 * Tests for the calibration dialog:
 *   1. deriveScale with known pixel distance + real length returns the
 *      expected pixelsPerUnit ratio.
 *   2. Unit conversion round-trip (toMeters → fromMeters) is stable.
 *   3. Confirm button fires onConfirm with a ScaleConfig that matches
 *      the user's input once multiplied through the unit factor.
 */

// @ts-nocheck
import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { CalibrationDialog } from '../components/CalibrationDialog';
import {
  deriveScale,
  toMeters,
  fromMeters,
  formatScaleRatio,
  ratioFromScale,
} from '../../../modules/pdf-takeoff/data/scale-helpers';

describe('deriveScale', () => {
  it('returns the expected px-per-unit for a known pair', () => {
    // 500 pixels == 5 meters  →  100 px/m
    expect(deriveScale(500, 5).pixelsPerUnit).toBe(100);
  });

  it('handles the canonical 1:50 mapping used by the UI presets', () => {
    // 72 dpi / (0.0254 m/in * 50) = the `pixelsPerUnit` the preset buttons use.
    const pxPerM = 72 / (0.0254 * 50);
    const scale = { pixelsPerUnit: pxPerM, unitLabel: 'm' };
    expect(ratioFromScale(scale)).toBe(50);
    expect(formatScaleRatio(scale)).toBe('1:50');
  });

  it('falls back to 1 px/unit on zero input', () => {
    expect(deriveScale(0, 5).pixelsPerUnit).toBe(1);
    expect(deriveScale(500, 0).pixelsPerUnit).toBe(1);
  });
});

describe('unit round-trip', () => {
  it('converts meters ↔ meters identically', () => {
    expect(fromMeters(toMeters(7, 'm'), 'm')).toBeCloseTo(7, 10);
  });

  it('converts mm round-trip', () => {
    expect(fromMeters(toMeters(1234, 'mm'), 'mm')).toBeCloseTo(1234, 10);
  });

  it('converts ft round-trip', () => {
    expect(fromMeters(toMeters(10, 'ft'), 'ft')).toBeCloseTo(10, 10);
  });

  it('converts in round-trip', () => {
    expect(fromMeters(toMeters(120, 'in'), 'in')).toBeCloseTo(120, 10);
  });

  it('known feet-to-meters conversion', () => {
    // 1 ft == 0.3048 m
    expect(toMeters(1, 'ft')).toBeCloseTo(0.3048, 4);
  });
});

describe('CalibrationDialog', () => {
  it('confirm fires onConfirm with a ScaleConfig derived from input', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <CalibrationDialog
        pixelDistance={500}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    // Default unit is m, default real length is 1 — change to 5.
    const input = screen.getByTestId('calibration-length-input') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '5' } });
    fireEvent.click(screen.getByTestId('calibration-confirm'));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    const scale = onConfirm.mock.calls[0][0];
    expect(scale.pixelsPerUnit).toBe(100); // 500 px / 5 m
    expect(scale.unitLabel).toBe('m');
  });

  it('feet input is converted to meters before derivation', () => {
    const onConfirm = vi.fn();
    render(
      <CalibrationDialog
        pixelDistance={500}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );
    const unitSelect = screen.getByTestId('calibration-unit-select') as HTMLSelectElement;
    fireEvent.change(unitSelect, { target: { value: 'ft' } });
    const input = screen.getByTestId('calibration-length-input') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '10' } });
    fireEvent.click(screen.getByTestId('calibration-confirm'));

    const scale = onConfirm.mock.calls[0][0];
    // 10 ft == 3.048 m   →   500 / 3.048 ≈ 164.04 px/m
    expect(scale.pixelsPerUnit).toBeCloseTo(500 / (10 * 0.3048), 3);
  });

  it('confirm is disabled while the real-length input is non-positive', () => {
    const onConfirm = vi.fn();
    render(
      <CalibrationDialog
        pixelDistance={500}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );
    const input = screen.getByTestId('calibration-length-input') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '0' } });
    const confirm = screen.getByTestId('calibration-confirm') as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
  });

  it('Escape key closes the dialog', () => {
    const onCancel = vi.fn();
    render(
      <CalibrationDialog
        pixelDistance={500}
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );
    fireEvent.keyDown(screen.getByTestId('calibration-length-input'), {
      key: 'Escape',
    });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
