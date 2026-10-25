// @ts-nocheck
/**
 * The page, header, footer and watermark settings of the document appearance.
 *
 * The controls are grouped (page, header, footer, watermark), each control is
 * built from the server's options, the preview follows every one of them, and
 * the save carries them to the server. A server from before the settings
 * existed answers without them and the form must still render the defaults.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
  watermark_text: '',
  watermark_opacity: 14,
  watermark_layout: 'diagonal',
  page_orientation: 'portrait',
  header_show_contact: false,
  header_rule: true,
  page_number_format: 'page_of',
  print_stamp: 'auto',
  footer_show_registration: false,
};

vi.mock('../api', () => ({
  getDocumentAppearance: vi.fn(),
  getDocumentAppearanceOptions: vi.fn(),
  saveDocumentAppearance: vi.fn(),
  resetDocumentAppearance: vi.fn(),
}));

import { getDocumentAppearance, getDocumentAppearanceOptions, saveDocumentAppearance } from '../api';
import { DocumentAppearancePanel } from '../DocumentAppearancePanel';
import {
  MARGIN_PRESETS,
  pageNumberSample,
  printStampSample,
  sheetMm,
  withAppearanceDefaults,
} from '../documentPreviewLayout';
import { useAuthStore } from '@/stores/useAuthStore';

function renderPanel(placement = 'settings') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DocumentAppearancePanel placement={placement} />
    </QueryClientProvider>,
  );
}

describe('document appearance page settings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ userRole: 'admin' });
    getDocumentAppearance.mockResolvedValue({ ...LOOK });
    getDocumentAppearanceOptions.mockResolvedValue({
      page_sizes: ['A4', 'LETTER', 'LEGAL'],
      logo_alignments: ['left', 'center', 'right'],
      min_font_size: 7,
      max_font_size: 14,
      min_margin_mm: 8,
      max_margin_mm: 40,
      max_footer_text: 120,
      max_watermark_text: 40,
      min_watermark_opacity: 5,
      max_watermark_opacity: 40,
      page_orientations: ['portrait', 'landscape'],
      page_number_formats: ['page_of', 'page', 'short', 'number'],
      print_stamps: ['auto', 'none', 'date', 'datetime'],
      watermark_layouts: ['diagonal', 'horizontal'],
      defaults: LOOK,
    });
    saveDocumentAppearance.mockImplementation(async (next) => next);
  });

  it('groups the controls into page, header, footer and watermark', async () => {
    renderPanel();
    await screen.findByTestId('doc-appearance-panel');
    const page = screen.getByTestId('appearance-group-page');
    const header = screen.getByTestId('appearance-group-header');
    const footer = screen.getByTestId('appearance-group-footer');
    const mark = screen.getByTestId('appearance-group-watermark');

    expect(within(page).getByTestId('appearance-page-size')).toBeInTheDocument();
    expect(within(page).getByTestId('appearance-orientation')).toBeInTheDocument();
    expect(within(page).getByTestId('appearance-margin')).toBeInTheDocument();
    expect(within(header).getByTestId('appearance-logo-align')).toBeInTheDocument();
    expect(within(footer).getByTestId('appearance-footer-text')).toBeInTheDocument();
    expect(within(footer).getByTestId('appearance-print-stamp')).toBeInTheDocument();
    expect(within(footer).getByTestId('appearance-page-number-format')).toBeInTheDocument();
    expect(within(mark).getByTestId('appearance-watermark-opacity')).toBeInTheDocument();
    expect(within(mark).getByTestId('appearance-watermark-layout')).toBeInTheDocument();
  });

  it('is titled Documents and PDF in the settings tab', async () => {
    renderPanel('settings');
    expect(await screen.findByText('Documents and PDF')).toBeInTheDocument();
  });

  it('a margin preset sets the margin', async () => {
    renderPanel();
    const input = await screen.findByTestId('appearance-margin');
    fireEvent.click(screen.getByTestId('appearance-margin-preset-narrow'));
    expect(input).toHaveValue(MARGIN_PRESETS[0].mm);
    fireEvent.click(screen.getByTestId('appearance-margin-preset-wide'));
    expect(input).toHaveValue(MARGIN_PRESETS[2].mm);
  });

  it('turns the preview sheet with the orientation', async () => {
    renderPanel();
    const preview = await screen.findByTestId('appearance-preview');
    expect(parseFloat(preview.style.aspectRatio)).toBeLessThan(1);
    fireEvent.change(screen.getByTestId('appearance-orientation'), { target: { value: 'landscape' } });
    expect(parseFloat(preview.style.aspectRatio)).toBeGreaterThan(1);
  });

  it('the header switches show the contact block and drop the rule in the preview', async () => {
    renderPanel();
    await screen.findByTestId('appearance-preview');
    expect(screen.queryByTestId('appearance-preview-contact')).toBeNull();
    expect(screen.getByTestId('appearance-preview-rule')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('switch', { name: /Company address and contact in the header/ }));
    expect(screen.getByTestId('appearance-preview-contact')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('switch', { name: /Line under the header/ }));
    expect(screen.queryByTestId('appearance-preview-rule')).toBeNull();
  });

  it('the footer settings change the page number, the stamp and the registration line', async () => {
    renderPanel();
    await screen.findByTestId('appearance-preview');
    expect(screen.getByTestId('appearance-preview-page-number')).toHaveTextContent('Page 1 of 3');
    expect(screen.getByTestId('appearance-preview-footer')).toHaveTextContent('Generated 2026-01-01');
    expect(screen.queryByTestId('appearance-preview-footer-2')).toBeNull();

    fireEvent.change(screen.getByTestId('appearance-page-number-format'), { target: { value: 'short' } });
    expect(screen.getByTestId('appearance-preview-page-number')).toHaveTextContent('1 / 3');

    fireEvent.change(screen.getByTestId('appearance-print-stamp'), { target: { value: 'datetime' } });
    const second = screen.getByTestId('appearance-preview-footer-2');
    expect(second).toHaveTextContent('Printed: 2026-01-01 14:05 UTC');
    // The date moves to its own line, so the default line drops it.
    expect(screen.getByTestId('appearance-preview-footer')).not.toHaveTextContent('Generated');

    fireEvent.click(screen.getByRole('switch', { name: /Registration numbers in the footer/ }));
    expect(screen.getByTestId('appearance-preview-footer-2')).toHaveTextContent('Your registration numbers');
  });

  it('the watermark strength and direction follow into the preview', async () => {
    renderPanel();
    fireEvent.change(await screen.findByTestId('appearance-watermark'), { target: { value: 'DRAFT' } });
    fireEvent.change(screen.getByTestId('appearance-watermark-opacity'), { target: { value: '30' } });
    const mark = screen.getByTestId('appearance-preview-watermark').firstElementChild;
    expect(mark.style.opacity).toBe('0.3');
    expect(mark.style.transform).toContain('rotate');

    fireEvent.change(screen.getByTestId('appearance-watermark-layout'), { target: { value: 'horizontal' } });
    expect(screen.getByTestId('appearance-preview-watermark').firstElementChild.style.transform).toBe('');
  });

  it('saves the new settings with the rest of the look', async () => {
    renderPanel();
    fireEvent.change(await screen.findByTestId('appearance-orientation'), { target: { value: 'landscape' } });
    fireEvent.change(screen.getByTestId('appearance-print-stamp'), { target: { value: 'date' } });
    fireEvent.change(screen.getByTestId('appearance-watermark-opacity'), { target: { value: '25' } });
    fireEvent.click(screen.getByTestId('appearance-save'));
    await waitFor(() => expect(saveDocumentAppearance).toHaveBeenCalled());
    expect(saveDocumentAppearance.mock.calls[0][0]).toMatchObject({
      page_orientation: 'landscape',
      print_stamp: 'date',
      watermark_opacity: 25,
    });
  });

  it('a server without the new settings still renders the defaults', async () => {
    const old = { ...LOOK };
    for (const key of Object.keys(LOOK)) {
      if (!['accent_color', 'footer_color', 'base_font_size', 'page_size', 'margin_mm', 'logo_align', 'footer_text', 'show_page_numbers', 'show_letterhead', 'watermark_text'].includes(key)) delete old[key];
    }
    getDocumentAppearance.mockResolvedValue(old);
    renderPanel();
    expect(await screen.findByTestId('appearance-orientation')).toHaveValue('portrait');
    expect(screen.getByTestId('appearance-print-stamp')).toHaveValue('auto');
    expect(screen.getByTestId('appearance-save')).toBeDisabled();
  });

  it('shows the controls disabled to a non-admin', async () => {
    useAuthStore.setState({ userRole: 'editor' });
    renderPanel();
    expect(await screen.findByTestId('appearance-orientation')).toBeDisabled();
    expect(screen.getByTestId('appearance-watermark-opacity')).toBeDisabled();
  });
});

describe('document preview layout helpers', () => {
  it('turns the sheet for landscape and defaults an unknown size to A4', () => {
    expect(sheetMm('A4', 'landscape')).toEqual({ w: 297, h: 210 });
    expect(sheetMm('LETTER')).toEqual({ w: 216, h: 279 });
    expect(sheetMm('B5')).toEqual({ w: 210, h: 297 });
  });

  it('writes the page number the way the PDF does', () => {
    expect(pageNumberSample('page_of', 2, 5)).toBe('Page 2 of 5');
    expect(pageNumberSample('page', 2, 5)).toBe('Page 2');
    expect(pageNumberSample('short', 2, 5)).toBe('2 / 5');
    expect(pageNumberSample('number', 2, 5)).toBe('2');
  });

  it('prints a stamp only for the date modes', () => {
    expect(printStampSample('auto')).toBe('');
    expect(printStampSample('none')).toBe('');
    expect(printStampSample('date')).toBe('Printed: 2026-01-01');
    expect(printStampSample('datetime')).toContain('14:05 UTC');
  });

  it('fills a missing setting from the platform default and keeps a set one', () => {
    const look = withAppearanceDefaults({ ...LOOK, print_stamp: undefined, header_rule: false });
    expect(look.print_stamp).toBe('auto');
    expect(look.header_rule).toBe(false);
    expect(look.watermark_opacity).toBe(14);
  });
});
