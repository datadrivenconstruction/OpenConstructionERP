import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { SubmittalAttachments } from './SubmittalAttachments';

const api = vi.hoisted(() => ({
  fetchSubmittalAttachments: vi.fn(),
  uploadSubmittalAttachment: vi.fn(),
  deleteSubmittalAttachment: vi.fn(),
  downloadSubmittalAttachment: vi.fn(),
}));
vi.mock('./api', () => api);

const UPLOADED = {
  document_id: 'd1',
  label: 'shop-drawing.pdf',
  added_by: 'u1',
  added_at: '2026-11-10T08:00:00Z',
  downloadable: true,
  size_bytes: 2048,
};
const LINKED = { ...UPLOADED, document_id: 'd2', label: 'spec.docx', downloadable: false, size_bytes: null };

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SubmittalAttachments submittalId="s1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.fetchSubmittalAttachments.mockResolvedValue([UPLOADED, LINKED]);
  api.uploadSubmittalAttachment.mockResolvedValue(UPLOADED);
  api.deleteSubmittalAttachment.mockResolvedValue(undefined);
  api.downloadSubmittalAttachment.mockResolvedValue(undefined);
});

describe('<SubmittalAttachments>', () => {
  it('lists the attachments and offers a download only for uploaded files', async () => {
    renderPanel();
    expect(await screen.findByText('shop-drawing.pdf')).toBeTruthy();
    expect(screen.getByText('spec.docx')).toBeTruthy();
    expect(screen.getByTestId('submittal-attachment-download-d1')).toBeTruthy();
    expect(screen.queryByTestId('submittal-attachment-download-d2')).toBeNull();
  });

  it('downloads the chosen file', async () => {
    renderPanel();
    fireEvent.click(await screen.findByTestId('submittal-attachment-download-d1'));
    await waitFor(() => expect(api.downloadSubmittalAttachment).toHaveBeenCalledWith('s1', UPLOADED));
  });

  it('uploads the picked file', async () => {
    renderPanel();
    await screen.findByText('shop-drawing.pdf');
    const file = new File(['%PDF-1.4'], 'new.pdf', { type: 'application/pdf' });
    fireEvent.change(screen.getByTestId('submittal-attachment-input'), { target: { files: [file] } });
    await waitFor(() => expect(api.uploadSubmittalAttachment).toHaveBeenCalledWith('s1', file));
  });

  it('removes an attachment only after confirmation', async () => {
    renderPanel();
    fireEvent.click(await screen.findByTestId('submittal-attachment-delete-d1'));
    expect(api.deleteSubmittalAttachment).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByTestId('confirm-dialog-confirm'));
    await waitFor(() => expect(api.deleteSubmittalAttachment).toHaveBeenCalledWith('s1', 'd1'));
  });

  it('says so when nothing is attached', async () => {
    api.fetchSubmittalAttachments.mockResolvedValue([]);
    renderPanel();
    expect(await screen.findByText('No files attached yet.')).toBeTruthy();
  });
});
