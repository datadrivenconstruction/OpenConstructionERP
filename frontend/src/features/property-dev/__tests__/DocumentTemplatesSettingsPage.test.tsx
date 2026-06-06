// @ts-nocheck
/**
 * Worldwide parameterization regression tests for
 * ``DocumentTemplatesSettingsPage``.
 *
 * The page used to lock a tenant into one of 18 hardcoded ``doc_type``
 * slugs (UAE / RU / DE / IN biased — RERA, MAHARERA, 214-FZ, …).
 * Tenants in Brazil / Japan / Mexico / Vietnam / Australia who needed
 * ``escritura_publica`` / ``juyo_jiko_setsumeisho`` / ``acta_de_entrega``
 * couldn't upload a template against their actual doc_type. We replaced
 * the ``<select>`` dropdowns with a free-text combobox
 * (``<input list>`` + ``<datalist>``).
 *
 * These tests assert:
 *   1. The doc_type / entity inputs are free-text comboboxes, not
 *      whitelisted selects.
 *   2. Typing a jurisdiction-specific slug (``escritura_publica``) is
 *      accepted by React state and survives across re-renders.
 *   3. The backend-supplied preset list is rendered as
 *      ``<datalist><option>`` suggestions (so the user still gets a
 *      pick-list affordance without being constrained to it).
 *   4. ``has_pdf_renderer: true`` from the backend gates the Preview
 *      button on a non-default doc_type (no hardcoded slug set).
 *   5. ``has_pdf_renderer: false`` hides Preview for a custom row that
 *      uses a recognised slug (binary uploads).
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api', () => ({
  listDocumentTemplates: vi.fn(),
  listDevelopments: vi.fn().mockResolvedValue([]),
  uploadCustomDocumentTemplate: vi.fn(),
  deleteCustomDocumentTemplate: vi.fn(),
  customDocumentTemplateDownloadUrl: vi.fn(() => '/dl/x'),
  getCustomDocumentTemplateContent: vi.fn(),
  sampleDocumentPreview: vi.fn(),
  saveTextCustomDocumentTemplate: vi.fn(),
}));

import {
  listDocumentTemplates,
  uploadCustomDocumentTemplate,
} from '../api';
import { DocumentTemplatesSettingsPage } from '../DocumentTemplatesSettingsPage';

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DocumentTemplatesSettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Catalogue payload the page consumes — mirrors the v4.7 backend
 *  contract: ``has_pdf_renderer`` per entry + ``doc_type_presets`` /
 *  ``entity_presets`` lists for combobox suggestions. */
function catalogue(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    templates: [
      {
        doc_type: 'escritura_publica',
        title: 'Escritura Pública (Brasil)',
        description: 'Brazilian notarial deed',
        trigger: 'POST /sales-contracts/ → signed',
        entity: 'sales_contract',
        pages: '2+',
        is_custom: false,
        has_pdf_renderer: true,
      },
      {
        doc_type: 'reservation_receipt',
        title: 'Reservation Receipt',
        description: '',
        trigger: 'POST /reservations/',
        entity: 'reservation',
        pages: '1',
        is_custom: false,
        has_pdf_renderer: true,
      },
    ],
    locales: ['en', 'pt'],
    regulators: ['NONE', 'CONFEA'],
    doc_type_presets: ['custom', 'reservation_receipt', 'sales_contract'],
    entity_presets: ['custom', 'reservation', 'sales_contract'],
    variables: [],
    upload: { allowed_extensions: ['.html', '.md'], max_size_mb: 10 },
    ...overrides,
  };
}

describe('DocumentTemplatesSettingsPage - worldwide parameterization', () => {
  beforeEach(() => vi.clearAllMocks());

  it('upload form renders combobox inputs (not <select>) for doc_type and entity', async () => {
    (listDocumentTemplates as ReturnType<typeof vi.fn>).mockResolvedValue(
      catalogue(),
    );
    renderPage();

    const dt = await screen.findByTestId('custom-upload-doctype');
    const en = await screen.findByTestId('custom-upload-entity');
    // Combobox: must be an INPUT with a `list` attribute (datalist
    // backing), NOT a SELECT (which would constrain to a hardcoded set).
    expect(dt.tagName).toBe('INPUT');
    expect(dt.getAttribute('list')).toBeTruthy();
    expect(en.tagName).toBe('INPUT');
    expect(en.getAttribute('list')).toBeTruthy();
  });

  it('accepts a free-text doc_type slug a tenant typed (worldwide jurisdiction)', async () => {
    (listDocumentTemplates as ReturnType<typeof vi.fn>).mockResolvedValue(
      catalogue(),
    );
    (uploadCustomDocumentTemplate as ReturnType<typeof vi.fn>).mockResolvedValue(
      {
        id: 'tpl-1',
        doc_type: 'juyo_jiko_setsumeisho',
        title: 'Important Matters Explanation',
        is_custom: true,
        entity: 'sales_contract',
        trigger: 'manual',
        description: '',
        pages: '—',
      },
    );

    renderPage();

    // Wait until the upload form is wired.
    const dt = await screen.findByTestId('custom-upload-doctype');
    const en = await screen.findByTestId('custom-upload-entity');

    // Type a Japanese-jurisdiction slug — not in the original 18-slug
    // hardcoded list — into the combobox. The legacy <select> would
    // have silently rejected this (option not in <options>). The new
    // combobox keeps the user's input verbatim.
    fireEvent.change(dt, { target: { value: 'juyo_jiko_setsumeisho' } });
    fireEvent.change(en, { target: { value: 'sales_contract' } });

    expect((dt as HTMLInputElement).value).toBe('juyo_jiko_setsumeisho');
    expect((en as HTMLInputElement).value).toBe('sales_contract');
  });

  it('exposes backend-supplied presets as <datalist><option> suggestions', async () => {
    (listDocumentTemplates as ReturnType<typeof vi.fn>).mockResolvedValue(
      catalogue({
        doc_type_presets: [
          'custom',
          'escritura_publica',
          'juyo_jiko_setsumeisho',
          'acta_de_entrega',
        ],
      }),
    );
    renderPage();

    const dt = await screen.findByTestId('custom-upload-doctype');
    const listId = dt.getAttribute('list');
    expect(listId).toBeTruthy();

    // The form mounts with the fallback preset list (loading state),
    // then re-renders with the backend-supplied list once the query
    // resolves. Wait for the data-driven entry to land in the datalist
    // — that's the assertion that backend presets actually drive the
    // UI, not the frontend's bundled fallback.
    await waitFor(() => {
      const datalist = document.getElementById(listId!) as
        | HTMLDataListElement
        | null;
      expect(datalist).toBeTruthy();
      const values = Array.from(datalist!.querySelectorAll('option')).map(
        (o) => (o as HTMLOptionElement).value,
      );
      // Brazilian / Japanese / Mexican slugs surfaced from the backend
      // payload — invisible if the frontend was still hardcoding its
      // own list.
      expect(values).toContain('escritura_publica');
      expect(values).toContain('juyo_jiko_setsumeisho');
      expect(values).toContain('acta_de_entrega');
    });
  });

  it('Preview button is gated by backend has_pdf_renderer (no hardcoded slug set)', async () => {
    (listDocumentTemplates as ReturnType<typeof vi.fn>).mockResolvedValue(
      catalogue(),
    );
    renderPage();

    // ``escritura_publica`` is NOT in the legacy hardcoded
    // ``BUILTIN_DOC_TYPES`` set — Preview would have been hidden in
    // the pre-v4.7 build. With ``has_pdf_renderer: true``, the button
    // must be present.
    await waitFor(() =>
      expect(
        screen.getByTestId('preview-sample-escritura_publica'),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId('download-sample-escritura_publica'),
    ).toBeInTheDocument();
  });

  it('hides Preview button when has_pdf_renderer is explicitly false (custom binary)', async () => {
    (listDocumentTemplates as ReturnType<typeof vi.fn>).mockResolvedValue(
      catalogue({
        templates: [
          {
            id: 'tpl-bin',
            doc_type: 'reservation_receipt',
            title: 'Branded reservation receipt (.docx)',
            description: '',
            trigger: 'manual',
            entity: 'reservation',
            pages: '—',
            is_custom: true,
            has_pdf_renderer: false,
            content_type:
              'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            filename: 'r.docx',
          },
        ],
      }),
    );
    renderPage();

    // Wait until the (single) custom card has mounted. ``Download`` is
    // the always-available action for custom rows; Preview must be
    // ABSENT because the row is a binary upload.
    await waitFor(() =>
      expect(screen.getByTestId('download-custom-tpl-bin')).toBeInTheDocument(),
    );
    expect(
      screen.queryByTestId('preview-sample-reservation_receipt'),
    ).not.toBeInTheDocument();
  });
});
