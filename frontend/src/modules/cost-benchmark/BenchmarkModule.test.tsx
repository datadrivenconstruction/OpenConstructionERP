// @ts-nocheck
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import BenchmarkModule from './BenchmarkModule';
import {
  BENCHMARKS,
  BUILDING_TYPES,
  BENCHMARK_REGIONS,
  calculatePercentile,
  breakdownByElement,
} from './data/benchmarks';

// Phase 2/3 wiring: the page now lists the tenant's projects and fetches an
// own-portfolio distribution. Stub both so the unit render stays offline and
// the picker stays hidden (zero projects) - the page then behaves exactly as
// the manual-only flow these assertions were written against.
vi.mock('@/features/projects/api', () => ({
  projectsApi: { list: vi.fn().mockResolvedValue([]) },
}));
vi.mock('./api', () => ({
  fetchOwnPortfolio: vi.fn().mockResolvedValue(null),
}));

function renderModule() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  // The module renders the cases button, which reads the current location, so
  // this tree needs a router the same way the application gives it one.
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <BenchmarkModule />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe('BenchmarkModule', () => {
  it('should render the page header', () => {
    renderModule();
    // Regex tolerates identity-marker ZWJ/ZWNJ trailing the visible text.
    expect(screen.getByText(/Market benchmarks/)).toBeInTheDocument();
    expect(screen.getByText(/Compare your estimate/)).toBeInTheDocument();
  });

  it('should render all input controls', () => {
    renderModule();
    expect(screen.getByText('Building Type')).toBeInTheDocument();
    expect(screen.getByText('Region')).toBeInTheDocument();
    expect(screen.getByText(/Gross Floor Area/)).toBeInTheDocument();
    expect(screen.getByText(/Your Total Cost/)).toBeInTheDocument();
  });

  it('should show default values', () => {
    renderModule();
    expect(screen.getByDisplayValue('5000')).toBeInTheDocument();
    expect(screen.getByDisplayValue('13250000')).toBeInTheDocument();
  });

  it('should show cost per m2 result', () => {
    renderModule();
    // 13250000 / 5000 = 2650 EUR/m2. Issue #270: the per-unit suffix now
    // follows the measurement-system preference (metric default -> "m²",
    // imperial -> "ft²"), so match the metric-default label here.
    expect(screen.getByText('Your Cost / m²')).toBeInTheDocument();
  });

  it('should show percentile position', () => {
    renderModule();
    expect(screen.getByText('Percentile vs Industry')).toBeInTheDocument();
    // Should show P-something
    const pctEl = screen.getByText(/^P\d+$/);
    expect(pctEl).toBeInTheDocument();
  });

  it('should show difference from median', () => {
    renderModule();
    expect(screen.getByText('Difference from Median')).toBeInTheDocument();
  });

  it('should update when building type changes', () => {
    renderModule();
    const btSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(btSelect, { target: { value: 'hospital' } });
    // Should now show hospital benchmarks
    expect(screen.getByText(/Hospital, Germany/)).toBeInTheDocument();
  });

  it('should update when region changes', () => {
    renderModule();
    const regionSelect = screen.getAllByRole('combobox')[1];
    fireEvent.change(regionSelect, { target: { value: 'UK' } });
    // Should show UK region in the headings
    const ukMatches = screen.getAllByText(/United Kingdom/);
    expect(ukMatches.length).toBeGreaterThan(0);
  });

  it('should show all building types comparison', () => {
    renderModule();
    // The heading includes region, so use partial match
    const headingMatches = screen.getAllByText(/All Building Types/);
    expect(headingMatches.length).toBeGreaterThan(0);
    // Each building type should be listed (both in select + comparison list)
    for (const bt of BUILDING_TYPES) {
      const matches = screen.getAllByText(bt.label);
      expect(matches.length).toBeGreaterThan(0);
    }
  });

  it('should show disclaimer', () => {
    renderModule();
    expect(screen.getByText(/compiled from recognised public cost sources/)).toBeInTheDocument();
  });

  it('should show benchmark range details (Min, Q1, Median, Q3, Max)', () => {
    renderModule();
    expect(screen.getByText('Min')).toBeInTheDocument();
    expect(screen.getByText('Q1 (25th)')).toBeInTheDocument();
    expect(screen.getByText('Median')).toBeInTheDocument();
    expect(screen.getByText('Q3 (75th)')).toBeInTheDocument();
    expect(screen.getByText('Max')).toBeInTheDocument();
  });
});

describe('calculatePercentile', () => {
  const range = BENCHMARKS.DE.office;

  it('should return 0 for value at or below min', () => {
    expect(calculatePercentile(range.min, range)).toBe(0);
    expect(calculatePercentile(range.min - 100, range)).toBe(0);
  });

  it('should return 100 for value at or above max', () => {
    expect(calculatePercentile(range.max, range)).toBe(100);
    expect(calculatePercentile(range.max + 100, range)).toBe(100);
  });

  it('should return ~50 for value at median', () => {
    const pct = calculatePercentile(range.median, range);
    expect(pct).toBeCloseTo(50, 0);
  });

  it('should return ~25 for value at Q1', () => {
    const pct = calculatePercentile(range.q1, range);
    expect(pct).toBeCloseTo(25, 0);
  });

  it('should return ~75 for value at Q3', () => {
    const pct = calculatePercentile(range.q3, range);
    expect(pct).toBeCloseTo(75, 0);
  });

  it('should interpolate between quartiles', () => {
    const midQ1Median = (range.q1 + range.median) / 2;
    const pct = calculatePercentile(midQ1Median, range);
    expect(pct).toBeGreaterThan(25);
    expect(pct).toBeLessThan(50);
  });
});

describe('Benchmark data integrity', () => {
  it('should have data for all regions', () => {
    expect(Object.keys(BENCHMARKS)).toHaveLength(BENCHMARK_REGIONS.length);
  });

  it('should have data for all building types in each region', () => {
    for (const region of BENCHMARK_REGIONS) {
      const regionData = BENCHMARKS[region.id];
      for (const bt of BUILDING_TYPES) {
        expect(regionData[bt.id]).toBeDefined();
        expect(regionData[bt.id].min).toBeLessThan(regionData[bt.id].max);
      }
    }
  });

  it('should have monotonically increasing ranges (min < q1 < median < q3 < max)', () => {
    for (const region of BENCHMARK_REGIONS) {
      for (const bt of BUILDING_TYPES) {
        const r = BENCHMARKS[region.id][bt.id];
        expect(r.min).toBeLessThan(r.q1);
        expect(r.q1).toBeLessThan(r.median);
        expect(r.median).toBeLessThan(r.q3);
        expect(r.q3).toBeLessThan(r.max);
      }
    }
  });
});

describe('breakdownByElement (DIN 276 element split)', () => {
  it('rows sum back to the input cost/m2', () => {
    const r = BENCHMARKS.DE.office;
    const rows = breakdownByElement(2650, 'office', r.split);
    const sum = rows.reduce((s, x) => s + x.value, 0);
    expect(sum).toBeCloseTo(2650, 0);
  });

  it('covers both KG300 and KG400 with valid DIN codes for every type', () => {
    for (const bt of BUILDING_TYPES) {
      const split = BENCHMARKS.DE[bt.id].split;
      const rows = breakdownByElement(2000, bt.id, split);
      expect(rows.some((x) => x.kg === 'KG300')).toBe(true);
      expect(rows.some((x) => x.kg === 'KG400')).toBe(true);
      for (const row of rows) {
        expect(row.value).toBeGreaterThanOrEqual(0);
        expect(row.code).toMatch(/^\d{3}$/);
      }
    }
  });

  it('respects the KG300 / KG400 split totals', () => {
    const split = BENCHMARKS.DE.hospital.split;
    const rows = breakdownByElement(5000, 'hospital', split);
    const kg300 = rows.filter((x) => x.kg === 'KG300').reduce((s, x) => s + x.value, 0);
    const kg400 = rows.filter((x) => x.kg === 'KG400').reduce((s, x) => s + x.value, 0);
    expect(kg300).toBeCloseTo(5000 * split.kg300Pct, 0);
    expect(kg400).toBeCloseTo(5000 * split.kg400Pct, 0);
  });
});
