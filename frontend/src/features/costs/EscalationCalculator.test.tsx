// @ts-nocheck
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { EscalationCalculator } from './EscalationCalculator';

describe('EscalationCalculator', () => {
  it('should render with default values', () => {
    render(<EscalationCalculator />);
    expect(screen.getByText('Cost Escalation Calculator')).toBeInTheDocument();
    expect(screen.getByText('Region')).toBeInTheDocument();
    expect(screen.getByText('Base year')).toBeInTheDocument();
    expect(screen.getByText('Target year')).toBeInTheDocument();
  });

  it('should show year-by-year breakdown when base < target', () => {
    render(<EscalationCalculator />);
    // Default: base 2023, target 2026 — 3 years of breakdown
    const breakdownChips = screen.getAllByText(/\+[\d.]+%/);
    expect(breakdownChips.length).toBeGreaterThan(0);
  });

  it('should compute escalation factor > 1 for forward escalation', () => {
    render(<EscalationCalculator />);
    // Factor should be shown and > 1
    const factorEl = screen.getByText(/\d+\.\d+x/);
    expect(factorEl).toBeInTheDocument();
    const factorMatch = factorEl.textContent?.match(/([\d.]+)x/);
    expect(factorMatch).toBeTruthy();
    const factor = parseFloat(factorMatch![1]);
    expect(factor).toBeGreaterThan(1);
  });

  it('should show factor of 1 when base = target year', () => {
    render(<EscalationCalculator />);
    // Set both years to 2023
    const selects = screen.getAllByRole('combobox');
    // baseYear select and targetYear select — they're the 2nd and 3rd selects
    const baseYearSelect = selects[1];
    const targetYearSelect = selects[2];

    fireEvent.change(baseYearSelect, { target: { value: '2025' } });
    fireEvent.change(targetYearSelect, { target: { value: '2025' } });

    expect(screen.getByText(/1\.0000x/)).toBeInTheDocument();
  });

  it('should update when region changes', () => {
    render(<EscalationCalculator />);
    const regionSelect = screen.getAllByRole('combobox')[0];

    // Switch to UK
    fireEvent.change(regionSelect, { target: { value: 'UK' } });

    // Should still show a valid factor
    const factorEl = screen.getByText(/\d+\.\d+x/);
    expect(factorEl).toBeInTheDocument();
  });

  it('should use manual rate when checkbox is checked', () => {
    render(<EscalationCalculator />);

    // Check the manual rate checkbox
    const checkbox = screen.getByRole('checkbox');
    fireEvent.click(checkbox);

    // Manual rate input should appear
    expect(screen.getByPlaceholderText('5.0')).toBeInTheDocument();

    // Type a manual rate
    const manualInput = screen.getByPlaceholderText('5.0');
    fireEvent.change(manualInput, { target: { value: '10' } });

    // Factor should reflect 10% annual rate
    const factorEl = screen.getByText(/\d+\.\d+x/);
    const factorMatch = factorEl.textContent?.match(/([\d.]+)x/);
    const factor = parseFloat(factorMatch![1]);
    // 3 years at 10% = 1.1^3 = 1.331
    expect(factor).toBeCloseTo(1.331, 1);
  });

  it('should call onApply with escalated amount and factor', () => {
    const onApply = vi.fn();
    render(<EscalationCalculator baseAmount={50000} onApply={onApply} />);

    const applyButton = screen.getByText('Apply');
    fireEvent.click(applyButton);

    expect(onApply).toHaveBeenCalledWith(
      expect.any(Number),
      expect.any(Number),
    );
    const [escalated, factor] = onApply.mock.calls[0];
    expect(factor).toBeGreaterThan(1);
    expect(escalated).toBeGreaterThan(50000);
  });

  it('should show disclaimer text', () => {
    render(<EscalationCalculator />);
    expect(screen.getByText(/Based on published indices/)).toBeInTheDocument();
  });

  it('should accept custom base amount', () => {
    render(<EscalationCalculator baseAmount={200000} />);
    const amountInput = screen.getByDisplayValue('200000');
    expect(amountInput).toBeInTheDocument();
  });

  it('should update amount when user types', () => {
    render(<EscalationCalculator />);
    const amountInput = screen.getByDisplayValue('100000');
    fireEvent.change(amountInput, { target: { value: '250000' } });
    expect(screen.getByDisplayValue('250000')).toBeInTheDocument();
  });
});
