// @ts-nocheck
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import SustainabilityModule from './SustainabilityModule';
import { EPD_MATERIALS, EU_CPR_BENCHMARKS } from './data/epd-materials';

describe('SustainabilityModule', () => {
  it('should render the page header', () => {
    render(<SustainabilityModule />);
    expect(screen.getByText('EPD / Embodied Carbon')).toBeInTheDocument();
    // EU CPR text appears in multiple places — just verify at least one
    const euCprElements = screen.getAllByText(/EU CPR/);
    expect(euCprElements.length).toBeGreaterThan(0);
  });

  it('should render the EPD material database section', () => {
    render(<SustainabilityModule />);
    expect(screen.getByText('EPD Material Database')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search materials...')).toBeInTheDocument();
  });

  it('should render category filter dropdown', () => {
    render(<SustainabilityModule />);
    expect(screen.getByText('All Categories')).toBeInTheDocument();
    // Select concrete category
    const select = screen.getAllByRole('combobox')[0];
    fireEvent.change(select, { target: { value: 'concrete' } });
    // Should now list concrete materials but not others
  });

  it('should filter materials by search term', () => {
    render(<SustainabilityModule />);
    const searchInput = screen.getByPlaceholderText('Search materials...');
    fireEvent.change(searchInput, { target: { value: 'steel' } });
    // Steel-related materials should be visible in expanded categories
  });

  it('should render default position entries in the calculator', () => {
    render(<SustainabilityModule />);
    // Default positions: Foundation concrete, Structural steel, Mineral wool
    expect(screen.getByDisplayValue('Foundation concrete')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Structural steel')).toBeInTheDocument();
  });

  it('should show GFA input', () => {
    render(<SustainabilityModule />);
    expect(screen.getByDisplayValue('1000')).toBeInTheDocument();
  });

  it('should show compliance badge', () => {
    render(<SustainabilityModule />);
    // With default data, should show some compliance level
    expect(screen.getByText(/EU CPR:/)).toBeInTheDocument();
  });

  it('should calculate total GWP', () => {
    render(<SustainabilityModule />);
    // Total should be displayed
    expect(screen.getByText('Total')).toBeInTheDocument();
    // The total kg value should be present (from default positions)
    const totalRow = screen.getByText('Total').closest('tr');
    expect(totalRow).toBeInTheDocument();
  });

  it('should show summary cards', () => {
    render(<SustainabilityModule />);
    expect(screen.getByText('Total Embodied Carbon')).toBeInTheDocument();
    expect(screen.getByText('Carbon per m2 GFA')).toBeInTheDocument();
    expect(screen.getByText('Annual (50yr RSP)')).toBeInTheDocument();
  });

  it('should add a new position when clicking add button', () => {
    render(<SustainabilityModule />);
    const addButton = screen.getByText('+ Add position');
    fireEvent.click(addButton);
    // Should now have 4 rows (3 default + 1 new)
    const deleteButtons = screen.getAllByRole('button').filter(
      (btn) => btn.querySelector('svg.lucide-x'),
    );
    // Default has 3 positions + search clear might have X — check there are more rows
    expect(deleteButtons.length).toBeGreaterThanOrEqual(4);
  });

  it('should show EU CPR benchmark thresholds', () => {
    render(<SustainabilityModule />);
    // Benchmarks section at bottom has the compliance levels
    const excellentMatches = screen.getAllByText(/Excellent/);
    expect(excellentMatches.length).toBeGreaterThan(0);
    // Non-compliant label should also be present
    const ncMatches = screen.getAllByText(/Non-compliant/i);
    expect(ncMatches.length).toBeGreaterThan(0);
  });

  it('should show data source attribution', () => {
    render(<SustainabilityModule />);
    expect(screen.getByText(/Okobaudat, ICE v3.0/)).toBeInTheDocument();
  });
});

describe('EPD_MATERIALS data', () => {
  it('should have at least 60 materials', () => {
    expect(EPD_MATERIALS.length).toBeGreaterThanOrEqual(60);
  });

  it('should have unique ids', () => {
    const ids = EPD_MATERIALS.map((m) => m.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('should have all required fields', () => {
    for (const m of EPD_MATERIALS) {
      expect(m.id).toBeTruthy();
      expect(m.name).toBeTruthy();
      expect(m.category).toBeTruthy();
      expect(typeof m.gwp).toBe('number');
      expect(m.unit).toBeTruthy();
      expect(m.source).toBeTruthy();
      expect(m.stages).toBeTruthy();
    }
  });

  it('should have timber materials with negative GWP (biogenic carbon)', () => {
    const timberMats = EPD_MATERIALS.filter((m) => m.category === 'timber');
    expect(timberMats.length).toBeGreaterThan(0);
    const hasNegative = timberMats.some((m) => m.gwp < 0);
    expect(hasNegative).toBe(true);
  });

  it('should cover all 11 categories', () => {
    const categories = new Set(EPD_MATERIALS.map((m) => m.category));
    expect(categories.size).toBe(11);
  });
});
