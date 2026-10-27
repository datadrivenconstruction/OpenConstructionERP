// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The review shows each value with its confidence, highlights the source line,
// and keeps confirm closed while an error is open or a warning is not accepted.

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { QuoteReview } from './QuoteReview';
import * as api from './api';
import { confidenceBand, parseLocaleDecimal } from './format';

vi.mock('./api', async (orig) => ({
  ...(await orig<typeof api>()),
  confirmQuote: vi.fn(),
  updateQuote: vi.fn(),
  updateLine: vi.fn(),
}));

const field = (value: string, confidence = 0.9, line = 1) => ({
  value,
  confidence,
  anchor: { line },
  machine_value: value,
  source: value,
});

function quote(over: Partial<api.Quote> = {}): api.Quote {
  return {
    id: 'q1',
    project_id: 'p1',
    package_id: 'pk1',
    boq_id: null,
    supplier_name: 'Alder Facade Works',
    status: 'in_review',
    source_kind: 'text',
    original_filename: 'quote.txt',
    extraction_engine: 'rules',
    currency: 'EUR',
    quote_total: '1000.00',
    created_at: '',
    line_count: 1,
    open_findings: 0,
    locale: 'de',
    page_count: 0,
    has_file: false,
    header: { supplier: field('Alder Facade Works'), currency: field('EUR', 0.95, 2) },
    lines: [
      {
        id: 'L1',
        description: 'Curtain wall',
        quantity: '10',
        unit: 'm2',
        unit_rate: '100.00',
        total: '1000.00',
        confidence: 0.45,
        anchor: { line: 3 },
        source: '',
        reviewed: false,
        match: null,
        machine: {},
      },
    ],
    notes: [
      { id: 'N1', kind: 'exclusion', text: 'Scaffolding excluded', confidence: 0.8, anchor: { line: 4 }, acknowledged: false },
    ],
    document: {
      lines: [
        { text: 'Alder Facade Works', anchor: { line: 1 } },
        { text: 'Currency EUR', anchor: { line: 2 } },
        { text: 'Curtain wall 10 m2 100.00 1000.00', anchor: { line: 3 } },
        { text: 'Scaffolding excluded', anchor: { line: 4 } },
      ],
    },
    confirmation: {},
    tax: {},
    findings: [],
    ...over,
  };
}

function setup(q: api.Quote) {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <QuoteReview quote={q} />
    </QueryClientProvider>,
  );
}

describe('quote review', () => {
  beforeEach(() => {
    vi.mocked(api.confirmQuote).mockReset();
    vi.mocked(api.updateQuote).mockReset();
  });

  it('marks a low-confidence line and highlights its source line on click', () => {
    setup(quote());
    const row = screen.getByTestId('quote-line');
    expect(row.getAttribute('data-low')).toBe('true');
    fireEvent.click(row);
    const active = screen.getByTestId('quote-document').querySelector('[data-active]');
    expect(active?.textContent).toContain('Curtain wall 10 m2');
  });

  it('keeps confirm disabled while an error is open', () => {
    setup(quote({ findings: [{ rule_id: 'quote_capture.exclusions_acknowledged', severity: 'error', message: 'x', element_ref: 'N1' }] }));
    expect((screen.getByTestId('confirm-bid') as HTMLButtonElement).disabled).toBe(true);
  });

  it('confirms only after the warnings are accepted', async () => {
    vi.mocked(api.confirmQuote).mockResolvedValue({ target_id: 'b1', target: 'bid' });
    setup(quote({ findings: [{ rule_id: 'quote_capture.lines_matched', severity: 'warning', message: 'x', element_ref: 'L1' }] }));
    const btn = screen.getByTestId('confirm-bid') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    fireEvent.click(screen.getByTestId('accept-warnings'));
    expect(btn.disabled).toBe(false);
    fireEvent.click(btn);
    await waitFor(() => expect(api.confirmQuote).toHaveBeenCalledWith('q1', 'bid', true));
  });

  it('acknowledges an exclusion through the API', async () => {
    vi.mocked(api.updateQuote).mockResolvedValue(quote());
    setup(quote());
    fireEvent.click(screen.getByTestId('note-ack'));
    await waitFor(() => expect(api.updateQuote).toHaveBeenCalledWith('q1', { acknowledge_notes: ['N1'] }));
  });
});

describe('quote formatting', () => {
  it('bands confidence', () => {
    expect(confidenceBand(0.9)).toBe('high');
    expect(confidenceBand(0.75)).toBe('medium');
    expect(confidenceBand(0.4)).toBe('low');
  });

  it('reads numbers typed in German and English', () => {
    expect(parseLocaleDecimal('1.234,5', 'de-DE')).toBe('1234.5');
    expect(parseLocaleDecimal('1,234.5', 'en-US')).toBe('1234.5');
    expect(parseLocaleDecimal('abc', 'en-US')).toBeNull();
  });
});
