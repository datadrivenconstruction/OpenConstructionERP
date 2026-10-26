// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Addenda​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ and bidder Q&A panels: question lifecycle, anonymity of published answers, timeline, BOQ diff.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen,
  within, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import * as api from '../api';
import type { Addendum, Clarification } from '../api';
import { ClarificationsPanel } from '../ClarificationsPanel';
import { TimelineView } from '../TenderTimeline';
import { AddendumChanges, PendingFirms } from '../AddendumList';

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof api>()),
  listClarifications: vi.fn(),
  listRecipients: vi.fn(),
  publishClarification: vi.fn(),
}));

const clar = (over: Partial<Clarification>): Clarification => ({
  id: 'c1',
  package_id: 'p1',
  number: 1,
  question: 'Which rebar grade?',
  answer: null,
  status: 'open',
  recipient_id: 'r1',
  asked_by_email: 'a@firm.io',
  asked_at: '2026-10-01T10:00:00Z',
  answered_at: null,
  published_at: null,
  addendum_id: null,
  days_before_closing: 12,
  ...over,
});

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ClarificationsPanel packageId="p1" />
    </QueryClientProvider>,
  );
}

describe('ClarificationsPanel', () => {
  beforeEach(() => {
    vi.mocked(api.listRecipients).mockResolvedValue([{ id: 'r1', company_name: 'Alpha Build' } as never]);
    vi.mocked(api.publishClarification).mockResolvedValue(clar({ status: 'published' }));
  });

  it('shows the asker and a publish button for an answered question, with days before closing', async () => {
    vi.mocked(api.listClarifications).mockResolvedValue([clar({ status: 'answered', answer: 'B500B' })]);
    renderPanel();
    await waitFor(() => expect(screen.getByTestId('clarification-card')).toBeTruthy());
    await waitFor(() => expect(screen.getByTestId('clarification-asker').textContent).toContain('Alpha Build'));
    expect(screen.getByTestId('clarification-days').textContent).toContain('12');
    fireEvent.click(screen.getByText('Publish to all bidders'));
    await waitFor(() => expect(vi.mocked(api.publishClarification)).toHaveBeenCalledWith('p1', 'c1'));
  });

  it('never shows the asker once the answer is published', async () => {
    vi.mocked(api.listClarifications).mockResolvedValue([clar({ status: 'published', answer: 'B500B' })]);
    renderPanel();
    await waitFor(() => expect(screen.getByTestId('clarification-published-view')).toBeTruthy());
    // The record-a-question form still lists invited firms; the published Q&A must not.
    const published = within(screen.getByTestId('clarification-published-view'));
    expect(screen.queryByTestId('clarification-asker')).toBeNull();
    expect(published.queryByText(/Alpha Build/)).toBeNull();
    expect(published.queryByText(/a@firm\.io/)).toBeNull();
    expect(screen.queryByText('Publish to all bidders')).toBeNull();
  });
});

describe('TimelineView', () => {
  it('marks past and future events and prints the rules as data', () => {
    render(
      <TimelineView
        events={[
          { kind: 'issued', at: '2026-09-01T00:00:00Z', label: '', ref_id: null, past: true },
          { kind: 'closing', at: '2026-12-01T00:00:00Z', label: '', ref_id: null, past: false },
        ]}
        rules={{
          country_code: 'XX',
          label: 'Test rules',
          addendum_min_days_before_closing: 7,
          answer_min_days_before_closing: 6,
          questions_close_days_before_closing: 10,
          bid_validity_days: 60,
          extend_deadline_if_late_addendum: true,
          acknowledgement: '',
          public_notice_of_changes: '',
          source: 'Test source',
          statute_reference: '',
          confidence: 'high',
        }}
      />,
    );
    const events = screen.getAllByTestId('timeline-event');
    expect(events.map((e) => e.getAttribute('data-past'))).toEqual(['true', 'false']);
    const rules = screen.getByTestId('tender-rules');
    expect(rules.textContent).toContain('Test rules');
    expect(rules.textContent).toContain('60');
    expect(rules.textContent).toContain('Test source');
  });
});

describe('AddendumChanges', () => {
  const base = { id: 'a1', package_id: 'p1', revision_no: 2, title: 'T', body: null } as Addendum;

  it('renders the BOQ diff, revision badge, moved deadline and superseded documents', () => {
    render(
      <AddendumChanges
        addendum={{
          ...base,
          boq_revision_no: 3,
          previous_deadline: '2026-11-01T00:00:00Z',
          new_deadline: '2026-11-15T00:00:00Z',
          boq_changes: [
            { op: 'change', ordinal: '1.2', description: 'Slab', unit: 'm3', quantity_before: 10, quantity_after: 12 },
            { op: 'delete', ordinal: '1.3', description: 'Wall', unit: 'm2', quantity_before: 5 },
          ],
          document_changes: [{ drawing_number: 'A-101', title: 'Plan', revision: 'C', superseded: true }],
        }}
      />,
    );
    const rows = screen.getByTestId('addendum-boq-diff').querySelectorAll('tr');
    expect(rows).toHaveLength(2);
    expect(rows[0]!.getAttribute('data-op')).toBe('change');
    expect(rows[0]!.textContent).toContain('10 -> 12');
    expect(rows[1]!.textContent).toContain('5 -> -');
    expect(screen.getByText('BOQ rev 3')).toBeTruthy();
    expect(screen.getByTestId('addendum-deadline-moved')).toBeTruthy();
    expect(screen.getByText('Superseded')).toBeTruthy();
  });

  it('renders nothing for a plain text addendum', () => {
    const { container } = render(<AddendumChanges addendum={base} />);
    expect(container.innerHTML).toBe('');
  });
});

describe('PendingFirms', () => {
  it('counts acknowledged firms and names the pending ones', () => {
    render(
      <PendingFirms
        addendum={{ pending_recipient_ids: ['r2'] } as Addendum}
        recipients={[
          { id: 'r1', company_name: 'Alpha Build' } as never,
          { id: 'r2', company_name: 'Beta Steel' } as never,
        ]}
      />,
    );
    const el = screen.getByTestId('addendum-pending');
    expect(el.textContent).toContain('1 of 2 acknowledged');
    expect(el.textContent).toContain('Beta Steel');
  });
});
