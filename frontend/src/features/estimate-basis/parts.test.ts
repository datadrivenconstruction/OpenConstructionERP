// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
import { describe, expect, it } from 'vitest';
import type { EstimateBasisDocument, EstimateClassOption, QualificationItem } from './api';
import {
  basisFilename,
  editableBasisClasses,
  enabledItems,
  newManualItem,
  parseAccuracyPct,
  renderBasisMarkdown,
  type MarkdownLabels,
} from './parts';

const LABELS: MarkdownLabels = {
  inclusions: 'Inclusions',
  exclusions: 'Exclusions',
  assumptions: 'Assumptions',
  notes: 'Notes',
  none: 'None.',
  status: 'Status',
  generated: 'Generated',
  estimate: 'The estimate',
  total: 'Estimate total',
  directCost: 'Direct cost',
  markups: 'Markups',
  estimateClass: 'Estimate class',
  classNotStated: 'Not stated',
  expectedRange: 'Expected range',
  rangeTo: 'to',
  pricedAt: 'Prices current as of',
  provenance: 'Where the numbers came from',
  shareOfValue: 'Share of value',
  shareOfLines: 'Share of line items',
  familyMeasured: 'Measured from a drawing or model',
  familyImported: 'Imported from a supplied bill',
  familyCatalogue: 'From a cost database or assembly',
  familyManual: 'Entered by hand',
  marketConditions: 'Market conditions',
  contingencyRationale: 'Contingency rationale',
};

function item(over: Partial<QualificationItem>): QualificationItem {
  return {
    id: 'x',
    category: 'inclusion',
    text: 'text',
    trade_code: null,
    trade_label: null,
    basis: '',
    source: 'auto',
    enabled: true,
    ...over,
  };
}

function doc(over: Partial<EstimateBasisDocument>): EstimateBasisDocument {
  return {
    id: 'd1',
    project_id: 'p1',
    boq_id: null,
    title: 'Basis of estimate',
    status: 'draft',
    notes: '',
    inclusions: [],
    exclusions: [],
    assumptions: [],
    coverage: {
      present_trades: [],
      absent_trades: [],
      total_positions: 0,
      classified_positions: 0,
      unclassified_positions: 0,
      zero_rate_positions: 0,
      missing_quantity_positions: 0,
      provisional_positions: 0,
      by_others_positions: 0,
    },
    financials: {
      direct_cost: '',
      markups_total: '',
      grand_total: '',
      currency: '',
      is_mixed_currency: false,
      has_unresolved_escalation: false,
      markup_count: 0,
      boq_count: 0,
    },
    provenance: {
      buckets: [],
      families: [],
      total_positions: 0,
      priced_total: '0.00',
      share_basis: 'value',
      ai_position_count: 0,
      ai_total: '0.00',
      scored_position_count: 0,
      low_confidence_count: 0,
      low_confidence_total: '0.00',
      model_linked_positions: 0,
      stale_links: 0,
      broken_links: 0,
      suggestion: { suggested_class: 0, base_class: 0, reasons: [] },
    },
    currency: '',
    pricing_date: null,
    estimate_class: null,
    accuracy_low_pct: '',
    accuracy_high_pct: '',
    accuracy_low_amount: '',
    accuracy_high_amount: '',
    market_conditions: '',
    contingency_rationale: '',
    generated_at: null,
    created_at: null,
    updated_at: null,
    ...over,
  };
}

describe('editableBasisClasses', () => {
  it('keeps saveable AACE classes and their published bands without offering CCA values the PATCH rejects', () => {
    const option = (estimate_class: number | string, classification_system = 'aace'): EstimateClassOption => ({
      estimate_class, classification_system, label: String(estimate_class),
      accuracy_low: '-10%', accuracy_high: '+20%',
      definition_level_low: 10, definition_level_high: 40, methodology: '',
    });
    const aace = [1, 2, 3, 4, 5].map((value) => option(value));
    const catalog = [...aace, option('A', 'ca_cca'), option('D', 'ca_cca'),
      option(1, 'future_system'), option('3'), option(0), option(6), option(2.5)];
    expect(editableBasisClasses(catalog)).toEqual(aace);
    expect(catalog).toHaveLength(12);
  });
});

describe('enabledItems', () => {
  it('keeps only enabled lines', () => {
    const items = [item({ id: 'a' }), item({ id: 'b', enabled: false })];
    expect(enabledItems(items).map((i) => i.id)).toEqual(['a']);
  });
});

describe('renderBasisMarkdown', () => {
  it('renders the title, sections and only enabled lines', () => {
    const md = renderBasisMarkdown(
      doc({
        title: 'Tower A - Basis',
        inclusions: [item({ text: 'Building works included' })],
        exclusions: [
          item({ category: 'exclusion', text: 'VAT excluded' }),
          item({ category: 'exclusion', text: 'Hidden line', enabled: false }),
        ],
      }),
      LABELS,
    );
    expect(md).toContain('# Tower A - Basis');
    expect(md).toContain('## Inclusions');
    expect(md).toContain('- Building works included');
    expect(md).toContain('- VAT excluded');
    expect(md).not.toContain('Hidden line');
    // An empty section still renders with a "none" placeholder.
    expect(md).toContain('## Assumptions');
    expect(md).toContain('None.');
    // Trailing newline, single.
    expect(md.endsWith('\n')).toBe(true);
    expect(md.endsWith('\n\n')).toBe(false);
  });

  it('includes the notes section only when notes are present', () => {
    expect(renderBasisMarkdown(doc({ notes: '' }), LABELS)).not.toContain('## Notes');
    const withNotes = renderBasisMarkdown(doc({ notes: 'Client to confirm scope.' }), LABELS);
    expect(withNotes).toContain('## Notes');
    expect(withNotes).toContain('Client to confirm scope.');
  });

  it('weaves the generated timestamp into the meta line when set', () => {
    const md = renderBasisMarkdown(doc({ generated_at: '2026-07-08T10:00:00+00:00' }), LABELS);
    expect(md).toContain('Generated: 2026-07-08T10:00:00+00:00');
    expect(md).toContain('Status: draft');
  });

  it('leads with the figure the document qualifies', () => {
    const md = renderBasisMarkdown(
      doc({
        currency: 'EUR',
        financials: {
          direct_cost: '900000.00',
          markups_total: '100000.00',
          grand_total: '1000000.00',
          currency: 'EUR',
          is_mixed_currency: false,
          has_unresolved_escalation: false,
          markup_count: 2,
          boq_count: 1,
        },
        estimate_class: 3,
        accuracy_low_pct: '-20',
        accuracy_high_pct: '30',
        accuracy_low_amount: '800000.00',
        accuracy_high_amount: '1300000.00',
        pricing_date: '2026-06-30',
      }),
      LABELS,
    );
    expect(md).toContain('## The estimate');
    expect(md).toContain('- Estimate total: 1000000.00 EUR');
    expect(md).toContain('- Direct cost: 900000.00 EUR');
    expect(md).toContain('- Estimate class: 3 (-20% / 30%)');
    expect(md).toContain('- Expected range: 800000.00 EUR to 1300000.00 EUR');
    expect(md).toContain('- Prices current as of: 2026-06-30');
    // The figure comes before the qualifications it qualifies.
    expect(md.indexOf('## The estimate')).toBeLessThan(md.indexOf('## Inclusions'));
  });

  it('says so plainly when no class has been stated', () => {
    const md = renderBasisMarkdown(
      doc({
        financials: {
          direct_cost: '',
          markups_total: '',
          grand_total: '500.00',
          currency: 'GBP',
          is_mixed_currency: false,
          has_unresolved_escalation: false,
          markup_count: 0,
          boq_count: 1,
        },
      }),
      LABELS,
    );
    expect(md).toContain('- Estimate class: Not stated');
    expect(md).not.toContain('Expected range');
  });

  it('omits the estimate block entirely when there is no total to state', () => {
    // Better a document with no figure than one asserting a figure of zero.
    expect(renderBasisMarkdown(doc({}), LABELS)).not.toContain('## The estimate');
  });

  it('states where the numbers came from, and which share it is', () => {
    const base = doc({});
    const md = renderBasisMarkdown(
      doc({
        provenance: {
          ...base.provenance,
          share_basis: 'value',
          total_positions: 10,
          families: [
            { family: 'measured', position_count: 8, total: '800.00', share_pct: '80.0' },
            { family: 'manual', position_count: 2, total: '200.00', share_pct: '20.0' },
          ],
        },
      }),
      LABELS,
    );
    expect(md).toContain('## Where the numbers came from');
    expect(md).toContain('Share of value:');
    expect(md).toContain('- Measured from a drawing or model: 80.0%');
    expect(md).toContain('- Entered by hand: 20.0%');
  });

  it('names the count fallback when the bill carries no priced value', () => {
    const base = doc({});
    const md = renderBasisMarkdown(
      doc({
        provenance: {
          ...base.provenance,
          share_basis: 'count',
          total_positions: 4,
          families: [{ family: 'manual', position_count: 4, total: '0.00', share_pct: '100.0' }],
        },
      }),
      LABELS,
    );
    expect(md).toContain('Share of line items:');
    expect(md).not.toContain('Share of value:');
  });

  it("carries the estimator's two judgements, and only when written", () => {
    expect(renderBasisMarkdown(doc({}), LABELS)).not.toContain('## Market conditions');
    const md = renderBasisMarkdown(
      doc({
        market_conditions: 'Four returns on an open list.',
        contingency_rationale: 'Held pending the geotechnical report.',
      }),
      LABELS,
    );
    expect(md).toContain('## Market conditions');
    expect(md).toContain('Four returns on an open list.');
    expect(md).toContain('## Contingency rationale');
    expect(md).toContain('Held pending the geotechnical report.');
    // They qualify the whole document, so they follow the lists, not precede them.
    expect(md.indexOf('## Assumptions')).toBeLessThan(md.indexOf('## Market conditions'));
  });
});

describe('parseAccuracyPct', () => {
  it('reads the forms the class table publishes', () => {
    expect(parseAccuracyPct('-20%')).toBe('-20');
    expect(parseAccuracyPct('+30%')).toBe('30');
    expect(parseAccuracyPct('15')).toBe('15');
  });

  it('collapses anything unreadable to zero rather than guessing', () => {
    expect(parseAccuracyPct('')).toBe('0');
    expect(parseAccuracyPct(null)).toBe('0');
    expect(parseAccuracyPct(undefined)).toBe('0');
    expect(parseAccuracyPct('wide')).toBe('0');
  });
});

describe('basisFilename', () => {
  it('sanitises the title into a safe .md name', () => {
    expect(basisFilename('Tower A / Phase 1')).toBe('basis_of_estimate_Tower_A_-_Phase_1.md');
  });

  it('falls back when the title is empty', () => {
    expect(basisFilename('')).toBe('basis_of_estimate_document.md');
    expect(basisFilename('   ')).toBe('basis_of_estimate_document.md');
  });
});

describe('newManualItem', () => {
  it('creates a blank, enabled, manual line in the given category', () => {
    const it2 = newManualItem('exclusion', 'manual-123');
    expect(it2).toEqual({
      id: 'manual-123',
      category: 'exclusion',
      text: '',
      trade_code: null,
      trade_label: null,
      basis: 'manual',
      source: 'manual',
      enabled: true,
    });
  });
});
