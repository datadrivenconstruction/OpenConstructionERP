import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const apiGet = vi.fn();
const apiPost = vi.fn();
vi.mock('@/shared/lib/api', () => ({
  apiGet: (...a: unknown[]) => apiGet(...a),
  apiPost: (...a: unknown[]) => apiPost(...a),
  apiPut: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));
vi.mock('@/shared/lib/documentExport', () => ({
  downloadRecordPdf: vi.fn(),
  downloadRegister: vi.fn(),
}));

import { RaiseNoticeButton } from './RaiseNoticeButton';

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <RaiseNoticeButton projectId="p1" sourceType="rfi" sourceId="r1" sourceRef="RFI-7" title="Beam clash" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('RaiseNoticeButton', () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiPost.mockReset();
  });

  it('offers the button when no notice exists, posts the event, then links to the notice', async () => {
    apiGet.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
    apiPost.mockResolvedValue({ id: 'n1', code: 'NOT-0003' });
    renderIt();
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    await waitFor(() => expect((screen.getByTestId('raise-notice-button') as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByTestId('raise-notice-button'));
    const link = await screen.findByTestId('raise-notice-link');
    expect(apiPost).toHaveBeenCalledWith('/v1/variations/notices/from-field-event/', {
      project_id: 'p1',
      source_type: 'rfi',
      source_id: 'r1',
      source_ref: 'RFI-7',
      title: 'Beam clash',
      recipient_type: 'owner',
    });
    expect(link.textContent).toContain('NOT-0003');
    expect(link.getAttribute('href')).toBe('/variations?tab=notices&highlight=n1');
  });

  it('shows the link at once when a notice already exists', async () => {
    apiGet.mockResolvedValue({ items: [{ id: 'n9', code: 'NOT-0009' }], total: 1, offset: 0, limit: 50 });
    renderIt();
    await waitFor(() => expect(screen.getByTestId('raise-notice-link').textContent).toContain('NOT-0009'));
    expect(screen.queryByTestId('raise-notice-button')).toBeNull();
    expect(apiGet.mock.calls[0]![0]).toBe('/v1/variations/notices/by-source/rfi/r1?project_id=p1');
  });
});
