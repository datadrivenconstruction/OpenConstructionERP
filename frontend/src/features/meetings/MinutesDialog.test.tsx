// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for the Export PDF action of <MinutesDialog>.
//
// The PDF is rendered on the server from the saved minutes row. The dialog
// keeps the draft in local state and only writes it on Save draft or on Issue
// minutes. Export did neither, so a user who typed into the draft and pressed
// Export got a file holding the previous save while the screen in front of
// them showed the new text. Neither side said anything was wrong.
//
// The evidence that this was an oversight rather than a decision sits in the
// same file: issueMut already persists first, and carries a comment saying why
// it has to. Export now does the same three lines.
//
// Both directions are covered here. The first case fails on the previous
// commit, where the only call is the PDF fetch and the typed text never leaves
// the browser. The second is the control: once the minutes are issued every
// field is disabled and the issue itself persisted, so an export that wrote
// anyway would be a pointless round trip against a row nobody can change.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', () => ({
  fetchMinutes: vi.fn(),
  updateMinutes: vi.fn(),
  issueMinutes: vi.fn(),
  generateMinutes: vi.fn(),
  distributeMinutes: vi.fn(),
  getMinutesPdfUrl: (id: string) => `/api/v1/meetings/${id}/minutes/export/pdf`,
}));

vi.mock('@/shared/lib/api', () => ({ triggerDownload: vi.fn() }));

vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: { getState: () => ({ accessToken: 'test-token' }) },
}));

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: () => void }) => unknown) => sel({ addToast: vi.fn() }),
}));

// Not part of what is being asserted, and it drags in the whole publishing
// feature if left real.
vi.mock('@/features/record-publishing/PublishRecordModal', () => ({
  PublishRecordModal: () => null,
}));

import { MinutesDialog } from './MinutesDialog';
import * as api from './api';
import type { Minutes } from './api';

const fetchMock = vi.mocked(api.fetchMinutes);
const updateMock = vi.mocked(api.updateMinutes);

const SAVED_SUMMARY = 'Piling rig arrives Monday.';
const TYPED_SUMMARY = 'Piling rig arrives Monday, crane on Wednesday.';

/** What the server holds. Everything the dialog reads, nothing it does not. */
function minutes(over: Partial<Minutes> = {}): Minutes {
  return {
    id: 'min-1',
    project_id: 'p-1',
    meeting_id: 'm-1',
    status: 'draft',
    content: {
      title: 'Site progress meeting 14',
      meeting_number: '14',
      meeting_type: 'progress',
      meeting_date: '2026-09-01',
      location: 'Site office',
      chairperson: 'R. Halloran',
      attendees_present: [],
      attendees_absent: [],
      agenda: [],
      action_items: [],
      decisions: [],
      next_meeting_date: null,
      summary: SAVED_SUMMARY,
      generated_at: '2026-09-01T10:00:00Z',
    },
    next_meeting_date: null,
    issued_at: null,
    issued_by: null,
    distributed_at: null,
    distributed_to: [],
    created_at: '2026-09-01T10:00:00Z',
    updated_at: '2026-09-01T10:00:00Z',
    ...over,
  };
}

/** Every call that leaves the browser, in the order it left. */
let calls: string[] = [];

function renderDialog() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MinutesDialog
        meetingId="m-1"
        projectId="p-1"
        meetingTitle="Site progress meeting 14"
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

function summaryBox(value: string): HTMLTextAreaElement {
  const box = screen
    .getAllByRole('textbox')
    .find((el): el is HTMLTextAreaElement => (el as HTMLTextAreaElement).value === value);
  if (!box) throw new Error(`no textbox holds ${JSON.stringify(value)}`);
  return box;
}

function exportButton(): HTMLButtonElement {
  return screen.getByRole('button', { name: /Export PDF/i }) as HTMLButtonElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  calls = [];

  updateMock.mockImplementation(async (_id, payload) => {
    calls.push('save');
    return minutes({ content: { ...minutes().content, ...payload.content } });
  });

  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      calls.push('pdf');
      return {
        ok: true,
        blob: async () => new Blob(['%PDF-1.4'], { type: 'application/pdf' }),
        headers: { get: () => 'attachment; filename="minutes.pdf"' },
      } as unknown as Response;
    }),
  );
});

describe('<MinutesDialog> Export PDF', () => {
  it('sends the text on screen before asking the server to render it', async () => {
    fetchMock.mockResolvedValue(minutes());
    renderDialog();

    await waitFor(() => expect(summaryBox(SAVED_SUMMARY)).toBeTruthy());
    fireEvent.change(summaryBox(SAVED_SUMMARY), { target: { value: TYPED_SUMMARY } });

    fireEvent.click(exportButton());

    await waitFor(() => expect(calls).toEqual(['save', 'pdf']));

    // Order alone is not enough: a save that wrote the old text in the right
    // order would still hand the user a file that disagrees with the screen.
    expect(updateMock).toHaveBeenCalledTimes(1);
    const payload = updateMock.mock.calls[0]?.[1];
    expect(payload?.content?.summary).toBe(TYPED_SUMMARY);
  });

  it('writes nothing when the minutes are already issued', async () => {
    fetchMock.mockResolvedValue(minutes({ status: 'issued', issued_at: '2026-09-02T08:00:00Z' }));
    renderDialog();

    await waitFor(() => expect(exportButton()).toBeTruthy());
    fireEvent.click(exportButton());

    await waitFor(() => expect(calls).toEqual(['pdf']));
    expect(updateMock).not.toHaveBeenCalled();
  });
});
