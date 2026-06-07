// OpenConstructionERP — DataDrivenConstruction (DDC)
// Tests for the Stage 3 "why this rate" mapping trace (WP7, design 3.3 / 4.3).
//
// The matcher writes a three-pass trace (semantic -> unit/scale -> rate sanity)
// onto each matched group. This component renders that trace as a compact
// expandable per-pass story and shows a visible outlier badge (with a
// plain-words tooltip) when a rate falls outside the per-run benchmark band.
// AI proposes, the human confirms - so the trace and confidence stay in view.

import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';

import { MappingTrace, OutlierBadge } from '../MappingTrace';
import type { MappingTrace as MappingTraceData } from '../../api';

afterEach(cleanup);

/** The canonical three-pass trace shape the matcher persists (WP3). */
function threePassTrace(overrides: Partial<MappingTraceData> = {}): MappingTraceData {
  return {
    passes: [
      { pass: 'semantic', kept: 2, dropped: 0, notes: '2 grounded candidate(s) retrieved', benchmark: null },
      {
        pass: 'unit_scale',
        kept: 2,
        dropped: 1,
        notes: '1 dimensionally-incompatible candidate(s) demoted vs group unit m2',
        benchmark: null,
      },
      {
        pass: 'rate_sanity',
        kept: 2,
        dropped: 0,
        notes: '1 rate outlier(s) flagged against median band',
        benchmark: { trade: 'finishes', unit: 'm2', band_low: 0.5, band_high: 8.0, outliers: 1 },
      },
    ],
    final_method: 'vector',
    needs_human_reason: null,
    ...overrides,
  };
}

describe('MappingTrace (WP7)', () => {
  it('renders nothing when there is no trace yet (unmatched group)', () => {
    const { container } = render(<MappingTrace trace={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when the trace has no passes', () => {
    const { container } = render(
      <MappingTrace trace={{ passes: [], final_method: null, needs_human_reason: null }} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('lists the three named passes when expanded', () => {
    render(<MappingTrace trace={threePassTrace()} defaultOpen />);

    const passes = screen.getAllByTestId('aiest-trace-pass');
    expect(passes).toHaveLength(3);
    // Each pass row carries its pass name as a data attribute, in order.
    expect(passes.map((el) => el.getAttribute('data-pass'))).toEqual([
      'semantic',
      'unit_scale',
      'rate_sanity',
    ]);

    // Layperson labels for each pass are shown.
    expect(screen.getByText('Find candidates')).toBeInTheDocument();
    expect(screen.getByText('Reconcile units')).toBeInTheDocument();
    expect(screen.getByText('Sanity-check the rate')).toBeInTheDocument();

    // The backend per-pass notes ride through verbatim.
    expect(screen.getByText('2 grounded candidate(s) retrieved')).toBeInTheDocument();
    expect(screen.getByText('1 rate outlier(s) flagged against median band')).toBeInTheDocument();
  });

  it('is collapsed by default and toggles open on click', () => {
    render(<MappingTrace trace={threePassTrace()} />);

    // Collapsed: the per-pass rows are not in the DOM yet.
    expect(screen.queryByTestId('aiest-trace-pass')).not.toBeInTheDocument();

    const toggle = screen.getByRole('button', { name: /why this rate/i });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getAllByTestId('aiest-trace-pass')).toHaveLength(3);
  });

  it('shows the rate-sanity benchmark band only on the rate-sanity pass', () => {
    render(<MappingTrace trace={threePassTrace()} defaultOpen />);
    // The band copy is interpolated; the i18n test stub returns the raw
    // defaultValue, so the literal template with the placeholder is present.
    expect(screen.getByText(/Plausible band:/)).toBeInTheDocument();
  });

  it('surfaces the needs-human reason when every candidate is an outlier', () => {
    render(
      <MappingTrace
        trace={threePassTrace({
          final_method: 'manual',
          needs_human_reason: 'every candidate rate is a benchmark-band outlier',
        })}
        defaultOpen
      />,
    );
    expect(screen.getByText(/Parked for review/i)).toBeInTheDocument();
  });

  it('renders an unknown future pass name with the raw key, never blanks out', () => {
    render(
      <MappingTrace
        trace={{
          passes: [{ pass: 'mystery_pass', kept: 1, dropped: 0, notes: '', benchmark: null }],
          final_method: 'vector',
          needs_human_reason: null,
        }}
        defaultOpen
      />,
    );
    const passes = screen.getAllByTestId('aiest-trace-pass');
    expect(passes).toHaveLength(1);
    expect(passes[0]?.getAttribute('data-pass')).toBe('mystery_pass');
    expect(screen.getByText('mystery_pass')).toBeInTheDocument();
  });
});

describe('OutlierBadge (WP7)', () => {
  it('renders a labelled badge with a plain-words tooltip', () => {
    render(<OutlierBadge />);
    const badge = screen.getByTestId('aiest-outlier-badge');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('Rate outlier');
    // The tooltip explains, in plain words, that the rate is kept but flagged.
    expect(badge.getAttribute('title')).toMatch(/far from the typical price/i);
    expect(badge.getAttribute('title')).toMatch(/kept the real rate/i);
  });
});
