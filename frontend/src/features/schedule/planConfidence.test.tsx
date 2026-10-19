// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { TFunction } from 'i18next';
import {
  ConfidenceBadge,
  activityConfidence,
  confidenceBand,
  confidenceReasonText,
  confidenceTooltip,
  formatScore,
} from './planConfidence';
import { GenerationPreviewPanel } from './GenerationPreviewPanel';
import type { GenerationPreview } from './api';

// Hoisted with the mock below, which vitest lifts above every other line.
const { fill } = vi.hoisted(() => ({
  fill: (key: string, options?: Record<string, unknown>) =>
    String(options?.defaultValue ?? key).replace(/\{\{(\w+)\}\}/g, (_, field: string) => String(options?.[field] ?? '')),
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: fill }) }));
const t = fill as unknown as TFunction;

afterEach(cleanup);

describe('reading the confidence a generated task carries', () => {
  it('reads a stored confidence and fills a missing band from the score', () => {
    const c = activityConfidence({ confidence: { score: 0.46, reasons: ['duration_estimated_fallback', 7] } });
    expect(c?.band).toBe('low');
    expect(c?.reasons).toEqual(['duration_estimated_fallback']);
  });

  it('ignores activities without one', () => {
    expect(activityConfidence(null)).toBeNull();
    expect(activityConfidence({ duration_source: 'labor_hours' })).toBeNull();
    expect(activityConfidence({ confidence: { score: 'x' } })).toBeNull();
  });

  it('uses the same bands as the server', () => {
    expect(confidenceBand(0.7)).toBe('high');
    expect(confidenceBand(0.69)).toBe('medium');
    expect(confidenceBand(0.5)).toBe('medium');
    expect(confidenceBand(0.49)).toBe('low');
    expect(formatScore(0.5)).toBe('0.50');
  });

  it('words every reason the server writes and drops unknown ones', () => {
    for (const code of [
      'duration_labor_hours',
      'duration_resource_sum',
      'duration_machine_hours',
      'duration_spans_works',
      'duration_estimated_fallback',
      'duration_cost_proportional',
      'duration_default_minimum',
      'capped_by_price',
      'unverified_norm',
      'shortened',
      'logic_bill_order',
      'logic_spans_works',
      'breakdown_lump_sum',
      'breakdown_whole_position',
    ]) {
      expect(confidenceReasonText(t, code)).toBeTruthy();
    }
    expect(confidenceReasonText(t, 'something_new')).toBeNull();
  });

  it('puts the score and the reasons in the badge tooltip, and marks low ones', () => {
    const c = activityConfidence({
      confidence: { score: 0.32, band: 'low', reasons: ['duration_cost_proportional', 'breakdown_lump_sum'] },
    })!;
    expect(confidenceTooltip(t, c)).toContain('0.32 (low)');
    render(<ConfidenceBadge confidence={c} />);
    const badge = screen.getByTestId('confidence-badge');
    expect(badge.dataset.band).toBe('low');
    expect(badge.textContent).toBe('0.32');
    expect(badge.getAttribute('title')).toContain('A lump sum, not broken down by quantity');
  });
});

const preview: GenerationPreview = {
  boq_id: 'b1',
  boq_name: 'Bill',
  boq_estimate_type: null,
  activity_count: 6,
  positions_scheduled: 3,
  lump_sum_positions: 0,
  summary_count: 1,
  estimated_count: 1,
  skipped_count: 1,
  note_counts: {},
  crews: 1,
  compressed_pct: null,
  fits: true,
  planned_start: '2026-05-04',
  planned_end: '2026-06-04',
  requested_end: null,
  warnings: [],
  existing_activity_count: 0,
  existing_started_count: 0,
  notes: [
    {
      position_id: 'p2',
      ordinal: '01.002',
      description: 'Excavation',
      note: 'machine_bound',
      days: 12,
      basis: { unit: '', rate: 0, hours: 0, gang: 0, hours_per_day: 8, machine_hours: 95.6, machines: 1 },
    },
  ],
  confidence: {
    score: 0.58,
    band: 'medium',
    counts: { high: 1, medium: 1, low: 1 },
    low: [
      {
        position_id: 'p3',
        ordinal: '01.003',
        description: 'Plaster',
        score: 0.46,
        reasons: ['duration_estimated_fallback', 'logic_bill_order'],
        total: '200',
      },
    ],
    low_total: 1,
  },
  cost: { boq_total: '1250.50', planned_total: '1000', loaded_tasks: 3, unscheduled_positions: 1, currency: 'EUR' },
  validation: {
    rule_sets: ['schedule_quality', 'schedule_5d'],
    errors: 1,
    warnings: 1,
    infos: 0,
    findings: [
      {
        rule_id: 'schedule_5d.cost_reconciliation',
        severity: 'error',
        message: 'The schedule carries 1,000.00 of the bill\'s 1,250.50',
        suggestion: 'Check the positions',
        position_id: null,
        ordinal: '',
      },
      {
        rule_id: 'schedule_5d.boq_coverage',
        severity: 'warning',
        message: "Position 01.004 'Fence' (250.50) is priced in the bill, but no activity carries it",
        suggestion: null,
        position_id: 'p4',
        ordinal: '01.004',
      },
    ],
  },
};

describe('the generation preview shows confidence, cost and checks before confirming', () => {
  it('names the plan confidence, the spread and the positions to review first', () => {
    render(<GenerationPreviewPanel preview={preview} />);
    const section = screen.getByTestId('generation-preview-confidence');
    expect(section.textContent).toContain('Plan confidence: 0.58 (medium).');
    expect(section.textContent).toContain('high 1, medium 1, low 1');
    const low = screen.getByTestId('generation-preview-low-confidence');
    expect(low.textContent).toContain('01.003');
    expect(low.textContent).toContain('Duration guessed from the unit, no labour norm');
  });

  it('says how much of the bill is cost-loaded and what is missing', () => {
    render(<GenerationPreviewPanel preview={preview} />);
    const cost = screen.getByTestId('generation-preview-cost');
    expect(cost.textContent).toContain('Positions with a price that are not in the plan: 1');
  });

  it('says a fully loaded bill is fully loaded', () => {
    render(
      <GenerationPreviewPanel
        preview={{ ...preview, cost: { ...preview.cost!, planned_total: '1250.5', unscheduled_positions: 0 } }}
      />,
    );
    expect(screen.getByTestId('generation-preview-cost').textContent).toContain('Markups are not included');
  });

  it('lists the findings, errors first, without blocking', () => {
    render(<GenerationPreviewPanel preview={preview} />);
    const checks = screen.getByTestId('generation-preview-checks');
    expect(checks.textContent).toContain('Errors: 1, warnings: 1. They do not stop you confirming.');
    const items = screen.getByTestId('generation-preview-findings').querySelectorAll('li');
    expect(items).toHaveLength(2);
    expect(items[0]?.textContent).toContain('The schedule carries');
  });

  it('says when the checks found nothing', () => {
    render(
      <GenerationPreviewPanel
        preview={{ ...preview, validation: { ...preview.validation!, errors: 0, warnings: 0, findings: [] } }}
      />,
    );
    expect(screen.getByTestId('generation-preview-checks').textContent).toContain('nothing to fix');
  });

  it('explains a duration the machines set', () => {
    render(<GenerationPreviewPanel preview={preview} />);
    expect(screen.getByTestId('generation-preview-notes').textContent).toContain(
      '12 working days, set by about 96 machine hours on 1 machine(s)',
    );
  });

  it('lists more findings on request', () => {
    const many = Array.from({ length: 12 }, (_, i) => ({
      ...preview.validation!.findings[1]!,
      position_id: `p${i}`,
      message: `finding ${i}`,
    }));
    render(<GenerationPreviewPanel preview={{ ...preview, confidence: null, validation: { ...preview.validation!, findings: many } }} />);
    expect(screen.getByTestId('generation-preview-findings').querySelectorAll('li')).toHaveLength(10);
    fireEvent.click(screen.getByText('Show all'));
    expect(screen.getByTestId('generation-preview-findings').querySelectorAll('li')).toHaveLength(12);
  });

  it('renders an older preview without the new blocks', () => {
    render(<GenerationPreviewPanel preview={{ ...preview, confidence: undefined, cost: undefined, validation: undefined }} />);
    expect(screen.queryByTestId('generation-preview-confidence')).toBeNull();
    expect(screen.queryByTestId('generation-preview-cost')).toBeNull();
    expect(screen.queryByTestId('generation-preview-checks')).toBeNull();
  });
});
