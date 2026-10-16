// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Component tests for <DocumentTemplatesPanel>.
//
// What is worth pinning is the contract with the server, which replaces a
// type's override with whatever it is sent: the body must be exactly the
// pinned set, a pinned `false` included, or a field quietly stops being set.
// Around that: a type offers only the fields its generator reads, an unset
// field shows the value it inherits and cannot be typed into, the letterhead
// fields say why they are locked while nothing prints a letterhead, and a
// non-admin gets a readable panel rather than a dead one.
//
// The i18n mock in src/test/setup.ts returns the defaultValue, so the English
// copy below is what renders here.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Partial mock: the shared UI barrel reads API_BASE and ApiError at module-eval
// time. triggerDownload is the blocked-popup fallback of the sample button.
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn(), apiPut: vi.fn(), apiDelete: vi.fn(), triggerDownload: vi.fn() };
});

vi.mock('./documentTemplates', async () => {
  const actual = await vi.importActual<typeof import('./documentTemplates')>('./documentTemplates');
  return {
    ...actual,
    getDocumentTypes: vi.fn(),
    saveDocumentTypeOverride: vi.fn(),
    resetDocumentTypeOverride: vi.fn(),
    saveDocumentTypeSections: vi.fn(),
    fetchDocumentTypeSamplePdf: vi.fn(),
  };
});

vi.mock('./companyProfile', async () => {
  const actual = await vi.importActual<typeof import('./companyProfile')>('./companyProfile');
  return { ...actual, getCompanyProfile: vi.fn() };
});

vi.mock('@/features/property-dev/api', () => ({
  getDocumentAppearance: vi.fn(),
  getDocumentAppearanceOptions: vi.fn(),
}));

import { DocumentTemplatesPanel } from './DocumentTemplatesPanel';
import * as templatesApi from './documentTemplates';
import * as profileApi from './companyProfile';
import * as appearanceApi from '@/features/property-dev/api';
import { triggerDownload } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';

const getTypesMock = vi.mocked(templatesApi.getDocumentTypes);
const saveMock = vi.mocked(templatesApi.saveDocumentTypeOverride);
const resetMock = vi.mocked(templatesApi.resetDocumentTypeOverride);
const sampleMock = vi.mocked(templatesApi.fetchDocumentTypeSamplePdf);
const sectionsMock = vi.mocked(templatesApi.saveDocumentTypeSections);

const WORKSPACE: appearanceApi.DocumentAppearance = {
  accent_color: '#1a1a2e',
  footer_color: '#999999',
  base_font_size: 10,
  page_size: 'A4',
  margin_mm: 20,
  logo_align: 'left',
  footer_text: '',
  show_page_numbers: true,
  show_letterhead: true,
  watermark_text: '',
};

const PROFILE: profileApi.CompanyProfile = {
  document_logo_data_url: '',
  legal_name: 'Hochbau Nord GmbH',
  address: '',
  registration_line: '',
  phone: '',
  email: '',
  website: '',
};

const RFI: templatesApi.DocumentTypeEntry = {
  key: 'rfi',
  label: 'Request for information',
  label_key: 'settings.document_templates.types.rfi',
  fields: ['show_letterhead', 'logo_align', 'accent_color', 'footer_text', 'footer_color', 'show_page_numbers'],
  override: { accent_color: '#aa0000' },
  effective: { ...WORKSPACE, accent_color: '#aa0000' },
};

const PUNCH_LIST: templatesApi.DocumentTypeEntry = {
  key: 'punch_list',
  label: 'Punch list',
  label_key: 'settings.document_templates.types.punch_list',
  // `watermark` stands in for a field a newer server adds before this client
  // knows how to draw it.
  fields: ['show_letterhead', 'logo_align', 'accent_color', 'watermark'],
  override: {},
  effective: WORKSPACE,
};

const PURCHASE_ORDER: templatesApi.DocumentTypeEntry = {
  key: 'purchase_order',
  label: 'Purchase order',
  label_key: 'settings.document_templates.types.purchase_order',
  fields: ['show_letterhead'],
  override: {},
  effective: WORKSPACE,
  sections: ['line_items', 'notes', 'signatures'],
  hidden_sections: ['signatures'],
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DocumentTemplatesPanel />
    </QueryClientProvider>,
  );
}

async function openRow(key: string) {
  fireEvent.click(await screen.findByTestId(`doc-type-toggle-${key}`));
}

const field = (key: string, name: string) => screen.getByTestId(`doc-type-field-${key}-${name}`);
const pinBox = (key: string, name: string) =>
  screen.getByTestId(`doc-type-pin-${key}-${name}`) as HTMLInputElement;

function colourInput(key: string, name: string): HTMLInputElement {
  const input = field(key, name).querySelector('input[type="color"]');
  if (!(input instanceof HTMLInputElement)) throw new Error(`no colour input for ${name}`);
  return input;
}

describe('DocumentTemplatesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ userRole: 'admin' });
    useToastStore.setState({ toasts: [] });
    getTypesMock.mockResolvedValue([RFI, PUNCH_LIST]);
    vi.mocked(profileApi.getCompanyProfile).mockResolvedValue(PROFILE);
    vi.mocked(appearanceApi.getDocumentAppearance).mockResolvedValue(WORKSPACE);
    vi.mocked(appearanceApi.getDocumentAppearanceOptions).mockResolvedValue({
      page_sizes: ['A4', 'LETTER', 'LEGAL'],
      logo_alignments: ['left', 'center', 'right'],
      min_font_size: 7,
      max_font_size: 14,
      min_margin_mm: 8,
      max_margin_mm: 40,
      max_footer_text: 120,
      defaults: WORKSPACE,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('lists the sections a document carries and saves the ones switched off', async () => {
    getTypesMock.mockResolvedValue([RFI, PURCHASE_ORDER]);
    sectionsMock.mockResolvedValue({ ...PURCHASE_ORDER, hidden_sections: ['notes', 'signatures'] });
    renderPanel();
    await openRow('purchase_order');

    const notes = within(screen.getByTestId('doc-type-section-purchase_order-notes')).getByRole('switch');
    const signatures = within(screen.getByTestId('doc-type-section-purchase_order-signatures')).getByRole('switch');
    expect(notes).toHaveAttribute('aria-checked', 'true');
    expect(signatures).toHaveAttribute('aria-checked', 'false');

    const save = screen.getByTestId('doc-type-sections-save-purchase_order');
    expect(save).toBeDisabled();
    fireEvent.click(notes);
    await waitFor(() => expect(save).toBeEnabled());
    fireEvent.click(save);

    await waitFor(() => expect(sectionsMock).toHaveBeenCalledTimes(1));
    const [key, hidden] = sectionsMock.mock.calls[0]!;
    expect(key).toBe('purchase_order');
    expect([...hidden].sort()).toEqual(['notes', 'signatures']);
    await waitFor(() => expect(save).toBeDisabled());
    // The look's own save is untouched by a sections change.
    expect(saveMock).not.toHaveBeenCalled();
  });

  it('shows no sections block for a type that prints a fixed form', async () => {
    renderPanel();
    await openRow('rfi');
    expect(screen.queryByTestId('doc-type-sections-rfi')).toBeNull();
  });

  it('names each type and says whether it has a look of its own', async () => {
    renderPanel();

    const rfi = await screen.findByTestId('doc-type-row-rfi');
    expect(within(rfi).getByText('Request for information')).toBeInTheDocument();
    expect(screen.getByTestId('doc-type-status-rfi')).toHaveTextContent('Own look');
    expect(screen.getByTestId('doc-type-status-punch_list')).toHaveTextContent('Same as all documents');
  });

  it('offers only the fields the type prints with', async () => {
    renderPanel();
    await openRow('punch_list');

    for (const name of ['show_letterhead', 'logo_align', 'accent_color']) {
      expect(field('punch_list', name)).toBeInTheDocument();
    }
    // The punch list draws no shared footer, so the footer fields would be
    // knobs that change nothing; the unknown field has no control to draw.
    for (const name of ['footer_text', 'footer_color', 'show_page_numbers', 'watermark']) {
      expect(screen.queryByTestId(`doc-type-field-punch_list-${name}`)).toBeNull();
    }
  });

  it('shows an unset field at the value it inherits, locked until it is set', async () => {
    renderPanel();
    await openRow('rfi');

    await waitFor(() => expect(colourInput('rfi', 'footer_color').value).toBe('#999999'));
    expect(colourInput('rfi', 'footer_color')).toBeDisabled();
    expect(pinBox('rfi', 'footer_color').checked).toBe(false);
    expect(within(field('rfi', 'footer_color')).getByText('Follows the look above')).toBeInTheDocument();

    expect(colourInput('rfi', 'accent_color').value).toBe('#aa0000');
    expect(colourInput('rfi', 'accent_color')).toBeEnabled();
    expect(pinBox('rfi', 'accent_color').checked).toBe(true);

    // Setting a field starts it at the inherited value, so ticking the box alone
    // does not change what prints.
    fireEvent.click(pinBox('rfi', 'footer_color'));
    expect(colourInput('rfi', 'footer_color')).toBeEnabled();
    expect(colourInput('rfi', 'footer_color').value).toBe('#999999');
  });

  it('saves exactly the pinned set, a pinned "off" included', async () => {
    saveMock.mockResolvedValue({
      ...RFI,
      override: { show_page_numbers: false },
      effective: { ...WORKSPACE, show_page_numbers: false },
    });
    renderPanel();
    await openRow('rfi');

    const save = screen.getByTestId('doc-type-save-rfi');
    expect(save).toBeDisabled();

    fireEvent.click(pinBox('rfi', 'accent_color'));
    fireEvent.click(pinBox('rfi', 'show_page_numbers'));
    fireEvent.click(within(field('rfi', 'show_page_numbers')).getByRole('switch'));
    await waitFor(() => expect(save).toBeEnabled());
    fireEvent.click(save);

    await waitFor(() => expect(saveMock).toHaveBeenCalledTimes(1));
    const [key, body] = saveMock.mock.calls[0]!;
    expect(key).toBe('rfi');
    // The server replaces the override with this body. The accent colour is
    // unpinned by leaving it out, and `false` is a setting, not an absence.
    expect(Object.keys(body)).toEqual(['show_page_numbers']);
    expect(body.show_page_numbers).toBe(false);
    await waitFor(() => expect(save).toBeDisabled());
    expect(screen.getByTestId('doc-type-status-rfi')).toHaveTextContent('Own look');
  });

  it('puts a type back on the look above', async () => {
    resetMock.mockResolvedValue({ ...RFI, override: {}, effective: WORKSPACE });
    renderPanel();
    await openRow('rfi');

    fireEvent.click(screen.getByTestId('doc-type-reset-rfi'));

    await waitFor(() => expect(resetMock).toHaveBeenCalledWith('rfi'));
    await waitFor(() =>
      expect(screen.getByTestId('doc-type-status-rfi')).toHaveTextContent('Same as all documents'),
    );
    expect(pinBox('rfi', 'accent_color').checked).toBe(false);
    expect(screen.getByTestId('doc-type-reset-rfi')).toBeDisabled();
    expect(saveMock).not.toHaveBeenCalled();
  });

  it('locks the letterhead fields while nothing prints a letterhead, and says why', async () => {
    vi.mocked(profileApi.getCompanyProfile).mockResolvedValue({ ...PROFILE, legal_name: '' });
    renderPanel();
    await openRow('punch_list');

    expect(await screen.findByTestId('doc-type-no-letterhead-punch_list')).toHaveTextContent(
      'Letterhead settings take effect once the company details above have a legal name or a document logo.',
    );
    for (const name of ['show_letterhead', 'logo_align', 'accent_color']) {
      expect(pinBox('punch_list', name)).toBeDisabled();
    }

    await openRow('rfi');
    // The footer does not depend on a letterhead.
    expect(pinBox('rfi', 'footer_color')).toBeEnabled();
    // A colour set before the letterhead went can still be cleared, but not edited.
    expect(pinBox('rfi', 'accent_color')).toBeEnabled();
    expect(colourInput('rfi', 'accent_color')).toBeDisabled();
  });

  it('shows a non-admin every look without a way to change it', async () => {
    useAuthStore.setState({ userRole: 'editor' });
    renderPanel();
    await openRow('rfi');

    expect(screen.queryByTestId('doc-type-save-rfi')).toBeNull();
    expect(screen.queryByTestId('doc-type-reset-rfi')).toBeNull();
    for (const name of RFI.fields) {
      expect(pinBox('rfi', name)).toBeDisabled();
    }
    expect(colourInput('rfi', 'accent_color').value).toBe('#aa0000');
    expect(screen.getByText('Only an admin can change this.')).toBeInTheDocument();
    // Reading the sample needs only sign-in.
    expect(screen.getByTestId('doc-type-sample-rfi')).toBeEnabled();
  });

  it("names the failure and carries the server's reason when a save is refused", async () => {
    saveMock.mockRejectedValue(new Error('Request for information documents do not use page_size.'));
    renderPanel();
    await openRow('rfi');

    fireEvent.click(pinBox('rfi', 'footer_color'));
    fireEvent.click(screen.getByTestId('doc-type-save-rfi'));

    await waitFor(() =>
      expect(useToastStore.getState().toasts).toContainEqual(
        expect.objectContaining({
          type: 'error',
          title: "Could not save this document's look",
          message: 'Request for information documents do not use page_size.',
        }),
      ),
    );
  });

  it('asks for the sample of the type and downloads it when the tab is blocked', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null);
    const blob = new Blob(['%PDF-1.4'], { type: 'application/pdf' });
    sampleMock.mockResolvedValue(blob);
    renderPanel();
    await openRow('rfi');

    fireEvent.click(screen.getByTestId('doc-type-sample-rfi'));

    await waitFor(() => expect(vi.mocked(triggerDownload)).toHaveBeenCalledWith(blob, 'sample-rfi.pdf'));
    expect(sampleMock).toHaveBeenCalledWith('rfi');
  });
});
