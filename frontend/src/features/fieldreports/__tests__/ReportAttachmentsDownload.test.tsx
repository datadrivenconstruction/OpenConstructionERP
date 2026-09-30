// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Opening a field report attachment.
//
// GET /api/v1/documents/{id}/download reads only the bearer header, and a plain
// <a href target=_blank> navigation never sends one, so every click opened a tab
// reading {"detail":"Not authenticated"}. The attachment is now a button that
// fetches with the token (downloadWithAuth), and a refusal shows a toast.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));

vi.mock('../api', () => ({
  fetchFieldReportTemplates: vi.fn(() => Promise.resolve([])),
  fetchReportDocuments: vi.fn(() =>
    Promise.resolve([
      { id: 'doc-1', name: 'slab.jpg', mime_type: 'image/jpeg', category: 'photo' },
    ]),
  ),
  linkReportDocuments: vi.fn(),
}));

vi.mock('@/features/documents/api', () => ({
  uploadDocument: vi.fn(),
  uploadPhoto: vi.fn(),
  deleteDocument: vi.fn(),
}));

vi.mock('../AttachExistingFileModal', () => ({ default: () => null }));

import { ReportAttachments } from '../ReportTemplateFields';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ReportAttachments reportId="rep-1" projectId="proj-1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useAuthStore.setState({ accessToken: 'tok-123' });
  vi.stubGlobal('fetch', mocks.fetch);
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:x');
  globalThis.URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  useAuthStore.setState({ accessToken: null });
});

describe('ReportAttachments', () => {
  it('renders the attachment as a button, not a link the browser would open without a token', async () => {
    mount();
    await screen.findByText('slab.jpg');
    expect(document.querySelector('a[href*="/api/"]')).toBeNull();
    expect(screen.getByText('slab.jpg').closest('button')).toBeTruthy();
  });

  it('fetches the download route with the bearer header', async () => {
    mocks.fetch.mockResolvedValue(
      new Response(new Blob(['x']), { status: 200, headers: { 'Content-Type': 'image/jpeg' } }),
    );
    mount();
    fireEvent.click(await screen.findByText('slab.jpg'));

    await waitFor(() => expect(mocks.fetch).toHaveBeenCalled());
    const [url, init] = mocks.fetch.mock.calls[0];
    expect(url).toBe('/api/v1/documents/doc-1/download');
    expect(init.headers.Authorization).toBe('Bearer tok-123');
  });

  it('shows a toast when the server refuses', async () => {
    mocks.fetch.mockResolvedValue(new Response(JSON.stringify({ detail: 'Not authenticated' }), { status: 401 }));
    mount();
    fireEvent.click(await screen.findByText('slab.jpg'));

    await waitFor(() =>
      expect(useToastStore.getState().toasts.some((t: { title?: string }) => t.title === 'Download failed')).toBe(true),
    );
  });
});
