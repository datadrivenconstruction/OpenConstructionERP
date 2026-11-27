// A certificate is awaiting review until a permitted member verifies it; others only see the state.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { useAuthStore } from '@/stores/useAuthStore';

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: () => void }) => unknown) => sel({ addToast: vi.fn() }),
}));

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return { ...actual, verifyCertificate: vi.fn().mockResolvedValue({}), unverifyCertificate: vi.fn() };
});

import { CertificateReview } from './CertificateReview';
import * as api from './api';

const cert = {
  id: 'c-1',
  cert_type: 'insurance',
  status: 'valid',
  review_status: 'awaiting_review',
  valid_until: '2027-06-01',
  metadata: { source_document_id: 'd-1' },
} as unknown as api.Certificate;

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CertificateReview cert={cert} label="Insurance" />
    </QueryClientProvider>,
  );
}

describe('CertificateReview', () => {
  beforeEach(() => vi.clearAllMocks());

  it('lets a manager verify an awaiting certificate', async () => {
    useAuthStore.setState({ userRole: 'manager' });
    wrap();
    expect(screen.getByTestId('certificate-review-status').textContent).toBe('Awaiting review');
    fireEvent.click(screen.getByText('Mark as verified'));
    await waitFor(() => expect(api.verifyCertificate).toHaveBeenCalledWith('c-1'));
  });

  it('hides the verify action from an editor', () => {
    useAuthStore.setState({ userRole: 'editor' });
    wrap();
    expect(screen.queryByText('Mark as verified')).toBeNull();
  });
});
