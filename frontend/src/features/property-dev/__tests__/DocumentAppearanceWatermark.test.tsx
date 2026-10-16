// @ts-nocheck
/**
 * The watermark field of the workspace document appearance.
 *
 * A preset fills the field with its word, the sheet preview shows the mark as
 * soon as there is one, and saving sends the text to the server with the rest
 * of the look. A server from before the field existed answers without it; the
 * form must still render and must not show a mark.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const LOOK = {
  accent_color: '#1a1a2e',
  footer_color: '#999999',
  base_font_size: 10,
  page_size: 'A4',
  margin_mm: 25,
  logo_align: 'left',
  footer_text: '',
  show_page_numbers: true,
  show_letterhead: true,
};

vi.mock('../api', () => ({
  getDocumentAppearance: vi.fn(),
  getDocumentAppearanceOptions: vi.fn(),
  saveDocumentAppearance: vi.fn(),
  resetDocumentAppearance: vi.fn(),
}));

import { getDocumentAppearance, getDocumentAppearanceOptions, saveDocumentAppearance } from '../api';
import { DocumentAppearancePanel } from '../DocumentAppearancePanel';
import { useAuthStore } from '@/stores/useAuthStore';

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DocumentAppearancePanel placement="settings" />
    </QueryClientProvider>,
  );
}

describe('document appearance watermark', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ userRole: 'admin' });
    getDocumentAppearanceOptions.mockResolvedValue({
      page_sizes: ['A4', 'LETTER', 'LEGAL'],
      logo_alignments: ['left', 'center', 'right'],
      min_font_size: 7,
      max_font_size: 14,
      min_margin_mm: 8,
      max_margin_mm: 40,
      max_footer_text: 120,
      max_watermark_text: 40,
      defaults: { ...LOOK, watermark_text: '' },
    });
  });

  it('a preset fills the field, shows the mark on the sheet and is saved', async () => {
    getDocumentAppearance.mockResolvedValue({ ...LOOK, watermark_text: '' });
    saveDocumentAppearance.mockImplementation(async (next) => next);
    renderPanel();

    const field = await screen.findByTestId('appearance-watermark');
    expect(field).toHaveValue('');
    expect(field).toHaveAttribute('maxLength', '40');
    expect(screen.queryByTestId('appearance-preview-watermark')).toBeNull();

    fireEvent.click(screen.getByTestId('appearance-watermark-preset-confidential'));
    expect(field).toHaveValue('CONFIDENTIAL');
    expect(screen.getByTestId('appearance-preview-watermark')).toHaveTextContent('CONFIDENTIAL');

    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => expect(saveDocumentAppearance).toHaveBeenCalled());
    expect(saveDocumentAppearance.mock.calls[0][0]).toMatchObject({ watermark_text: 'CONFIDENTIAL' });
  });

  it('a server without the field still renders an empty watermark and no mark', async () => {
    getDocumentAppearance.mockResolvedValue({ ...LOOK });
    renderPanel();

    const field = await screen.findByTestId('appearance-watermark');
    expect(field).toHaveValue('');
    expect(screen.queryByTestId('appearance-preview-watermark')).toBeNull();
  });
});
