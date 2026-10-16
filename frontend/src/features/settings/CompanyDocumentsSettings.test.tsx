// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Component tests for <CompanyDocumentsSettings>.
//
// The tab exists because some firms may not send an RFI without their formal
// letterhead. What is worth pinning is therefore not that inputs render, but
// that the admin's edit reaches the server as a patch of just what changed,
// that the preview says what the PDF will print (and says so when it will
// print nothing), that a file the server would drop is refused in words before
// upload, and that a non-admin gets a readable page rather than a dead form.
//
// The i18n mock in src/test/setup.ts returns the defaultValue with its
// placeholders filled in, so the English copy below is what renders here.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Partial mock, as in EInvoiceSettings.test.tsx: the shared UI barrel drags in
// components that read API_BASE or ApiError at module-eval time. The branding
// store's server sync goes through these, so nothing here reaches a network.
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn(), apiPut: vi.fn(), apiDelete: vi.fn() };
});

vi.mock('./companyProfile', async () => {
  const actual = await vi.importActual<typeof import('./companyProfile')>('./companyProfile');
  return {
    ...actual,
    getCompanyProfile: vi.fn(),
    getCompanyProfileOptions: vi.fn(),
    saveCompanyProfile: vi.fn(),
    fetchSampleDocumentPdf: vi.fn(),
  };
});

// The appearance panel is reused from property development and calls these on
// mount; a factory mock answers only what it names.
vi.mock('@/features/property-dev/api', () => ({
  getDocumentAppearance: vi.fn(),
  getDocumentAppearanceOptions: vi.fn(),
  saveDocumentAppearance: vi.fn(),
  resetDocumentAppearance: vi.fn(),
}));

// The per-document section under the appearance panel lists its types on mount.
vi.mock('./documentTemplates', async () => {
  const actual = await vi.importActual<typeof import('./documentTemplates')>('./documentTemplates');
  return {
    ...actual,
    getDocumentTypes: vi.fn(),
    saveDocumentTypeOverride: vi.fn(),
    resetDocumentTypeOverride: vi.fn(),
    fetchDocumentTypeSamplePdf: vi.fn(),
  };
});

import { CompanyDocumentsSettings } from './CompanyDocumentsSettings';
import * as profileApi from './companyProfile';
import * as appearanceApi from '@/features/property-dev/api';
import * as templatesApi from './documentTemplates';
import { useAuthStore } from '@/stores/useAuthStore';
import { useBrandingStore } from '@/stores/useBrandingStore';
import { ApiError } from '@/shared/lib/api';

const getProfileMock = vi.mocked(profileApi.getCompanyProfile);
const getOptionsMock = vi.mocked(profileApi.getCompanyProfileOptions);
const saveProfileMock = vi.mocked(profileApi.saveCompanyProfile);
const sampleMock = vi.mocked(profileApi.fetchSampleDocumentPdf);

const BLANK: profileApi.CompanyProfile = {
  document_logo_data_url: '',
  legal_name: '',
  address: '',
  registration_line: '',
  phone: '',
  email: '',
  website: '',
};

const OPTIONS: profileApi.CompanyProfileOptions = {
  max_lengths: {
    legal_name: 120,
    address: 240,
    registration_line: 160,
    phone: 40,
    email: 120,
    website: 120,
  },
  max_address_lines: 3,
  // Small on purpose, so a size refusal needs only a two-kilobyte file. It
  // leaves room for 1479 bytes of image.
  max_logo_data_url_chars: 2000,
  logo_mime_types: ['image/png', 'image/jpeg', 'image/webp', 'image/svg+xml'],
};

const APPEARANCE: appearanceApi.DocumentAppearance = {
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

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CompanyDocumentsSettings />
    </QueryClientProvider>,
  );
}

/** The document slot takes files once the server's accepted types and cap arrive. */
async function documentSlotReady() {
  await within(await screen.findByTestId('logo-slot-document')).findByText(/up to .* MB/);
}

function fileInputOf(slotTestId: string): HTMLInputElement {
  const input = screen.getByTestId(slotTestId).querySelector('input[type="file"]');
  if (!(input instanceof HTMLInputElement)) throw new Error(`no file input in ${slotTestId}`);
  return input;
}

describe('CompanyDocumentsSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ userRole: 'admin' });
    useBrandingStore.setState({ mode: 'default', logoDataUrl: null, companyName: '' });
    getProfileMock.mockResolvedValue(BLANK);
    getOptionsMock.mockResolvedValue(OPTIONS);
    saveProfileMock.mockImplementation(async (patch) => ({ ...BLANK, ...patch }));
    vi.mocked(appearanceApi.getDocumentAppearance).mockResolvedValue(APPEARANCE);
    vi.mocked(appearanceApi.getDocumentAppearanceOptions).mockResolvedValue({
      page_sizes: ['A4', 'LETTER', 'LEGAL'],
      logo_alignments: ['left', 'center', 'right'],
      min_font_size: 7,
      max_font_size: 14,
      min_margin_mm: 8,
      max_margin_mm: 40,
      max_footer_text: 120,
      defaults: APPEARANCE,
    });
    vi.mocked(templatesApi.getDocumentTypes).mockResolvedValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('shows both logo slots, the app one and the document one', async () => {
    renderPanel();

    const app = await screen.findByTestId('logo-slot-app');
    const doc = screen.getByTestId('logo-slot-document');
    expect(within(app).getByText('Logo in the app (sidebar)')).toBeInTheDocument();
    expect(within(doc).getByText('Logo on documents')).toBeInTheDocument();
    expect(
      within(doc).getByText('Your formal logo for printed documents. If empty, the app logo is used.'),
    ).toBeInTheDocument();
  });

  it('says the app logo prints while the document slot is empty', async () => {
    useBrandingStore.setState({ mode: 'logo', logoDataUrl: 'data:image/png;base64,QUJD' });
    renderPanel();

    const doc = await screen.findByTestId('logo-slot-document');
    expect(
      within(doc).getByText('Documents print the app logo until you add one here.'),
    ).toBeInTheDocument();
  });

  it('saves only the fields that changed', async () => {
    getProfileMock.mockResolvedValue({ ...BLANK, phone: '+49 30 1234560' });
    renderPanel();

    const save = await screen.findByTestId('company-save');
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Legal company name'), {
      target: { value: 'Hochbau Nord GmbH' },
    });
    await waitFor(() => expect(save).toBeEnabled());
    fireEvent.click(save);

    await waitFor(() => expect(saveProfileMock).toHaveBeenCalledTimes(1));
    // A patch, not the record: the server merges it, so leaving the phone and
    // the logo out is what keeps them, and sending them would race a logo
    // upload saved a moment earlier.
    expect(saveProfileMock.mock.calls[0]![0]).toEqual({ legal_name: 'Hochbau Nord GmbH' });
    await waitFor(() => expect(save).toBeDisabled());
  });

  it('draws the typed legal name in the preview before it is saved', async () => {
    renderPanel();

    const input = await screen.findByLabelText('Legal company name');
    fireEvent.change(input, { target: { value: 'Hochbau Nord GmbH' } });

    const preview = screen.getByTestId('letterhead-preview');
    expect(within(preview).getByTestId('letterhead-preview-name')).toHaveTextContent('Hochbau Nord GmbH');
    expect(saveProfileMock).not.toHaveBeenCalled();
  });

  it('does not preview a letterhead the server would not print', async () => {
    // The server draws one only for a legal name or a document logo. An
    // address and a phone number alone would read as a tidy block here and as
    // nothing on paper, which is the one thing a preview must not do.
    useBrandingStore.setState({ mode: 'logo', logoDataUrl: 'data:image/png;base64,QUJD' });
    renderPanel();

    fireEvent.change(await screen.findByLabelText('Address'), {
      target: { value: '12 Harbour Road\nSpringfield' },
    });
    fireEvent.change(screen.getByLabelText('Phone'), { target: { value: '+1 555 0100' } });

    expect(screen.getByTestId('letterhead-preview-empty')).toBeInTheDocument();
    expect(screen.queryByText('12 Harbour Road')).toBeNull();
  });

  it('keeps the address to the lines the letterhead prints', async () => {
    renderPanel();

    const address = (await screen.findByLabelText('Address')) as HTMLTextAreaElement;
    fireEvent.change(address, { target: { value: 'one\ntwo\nthree\nfour' } });
    expect(address.value).toBe('one\ntwo\nthree');
  });

  it('follows the appearance switch in the preview without saving it', async () => {
    getProfileMock.mockResolvedValue({ ...BLANK, legal_name: 'Hochbau Nord GmbH' });
    renderPanel();

    await screen.findByTestId('letterhead-preview-name');
    fireEvent.click(
      await screen.findByRole('switch', { name: /Print the company letterhead on the first page/ }),
    );

    await screen.findByText('The letterhead is switched off in Document appearance below.');
    expect(screen.queryByTestId('letterhead-preview-name')).toBeNull();
    expect(appearanceApi.saveDocumentAppearance).not.toHaveBeenCalled();
  });

  it('refuses an oversized document logo in words, before uploading it', async () => {
    renderPanel();
    await documentSlotReady();

    const big = new File(['x'.repeat(2048)], 'logo.png', { type: 'image/png' });
    fireEvent.change(fileInputOf('logo-slot-document'), { target: { files: [big] } });

    const alert = await within(screen.getByTestId('logo-slot-document')).findByRole('alert');
    expect(alert.textContent).toMatch(/The limit is/);
    expect(saveProfileMock).not.toHaveBeenCalled();
  });

  it('refuses a file type the server would drop', async () => {
    renderPanel();
    await documentSlotReady();

    const gif = new File(['GIF89a'], 'logo.gif', { type: 'image/gif' });
    fireEvent.change(fileInputOf('logo-slot-document'), { target: { files: [gif] } });

    const alert = await within(screen.getByTestId('logo-slot-document')).findByRole('alert');
    expect(alert.textContent).toMatch(/not supported/);
    expect(saveProfileMock).not.toHaveBeenCalled();
  });

  it('uploads an accepted document logo on its own', async () => {
    renderPanel();
    await documentSlotReady();

    const png = new File(['PNGDATA'], 'logo.png', { type: 'image/png' });
    fireEvent.change(fileInputOf('logo-slot-document'), { target: { files: [png] } });

    await waitFor(() => expect(saveProfileMock).toHaveBeenCalledTimes(1));
    const patch = saveProfileMock.mock.calls[0]![0];
    expect(Object.keys(patch)).toEqual(['document_logo_data_url']);
    expect(patch.document_logo_data_url).toMatch(/^data:image\/png;base64,/);
  });

  it('says in the slot why the server refused a logo, in the words of the reader', async () => {
    // The server re-checks every logo and answers 422 with a reason, keeping
    // the stored one. The reason picks a translated sentence; the English
    // message in the detail is only a fallback and must not be what shows.
    saveProfileMock.mockRejectedValue(
      new ApiError(422, 'Unprocessable Entity', {
        detail: {
          error: 'invalid_document_logo',
          field: 'document_logo_data_url',
          reason: 'too_large',
          message: 'The document logo is too large: 2400 characters as a data URL, the limit is 2000.',
          accepted_types: OPTIONS.logo_mime_types,
          max_chars: 2000,
        },
      }),
    );
    renderPanel();
    await documentSlotReady();

    const png = new File(['PNGDATA'], 'logo.png', { type: 'image/png' });
    fireEvent.change(fileInputOf('logo-slot-document'), { target: { files: [png] } });

    const alert = await within(screen.getByTestId('logo-slot-document')).findByRole('alert');
    expect(alert.textContent).toMatch(/The limit is/);
    expect(alert.textContent).not.toMatch(/characters as a data URL/);
  });

  it('prints the address on one line when the letterhead is centred', async () => {
    vi.mocked(appearanceApi.getDocumentAppearance).mockResolvedValue({
      ...APPEARANCE,
      logo_align: 'center',
    });
    getProfileMock.mockResolvedValue({
      ...BLANK,
      legal_name: 'Hochbau Nord GmbH',
      address: 'Hafenstrasse 1\n24103 Kiel',
    });
    renderPanel();

    const preview = await screen.findByTestId('letterhead-preview');
    expect(await within(preview).findByText('Hafenstrasse 1 · 24103 Kiel')).toBeInTheDocument();
  });

  it('closes the tab it opened when the sample PDF cannot be fetched', async () => {
    const tab = { close: vi.fn(), location: { href: '' } };
    vi.spyOn(window, 'open').mockReturnValue(tab as unknown as Window);
    sampleMock.mockRejectedValue(new Error('Not Found'));
    renderPanel();

    fireEvent.click(await screen.findByTestId('company-open-sample'));

    await waitFor(() => expect(tab.close).toHaveBeenCalledTimes(1));
    expect(tab.location.href).toBe('');
  });

  it('shows a non-admin the same page read-only', async () => {
    useAuthStore.setState({ userRole: 'editor' });
    getProfileMock.mockResolvedValue({ ...BLANK, legal_name: 'Hochbau Nord GmbH' });
    renderPanel();

    await screen.findByTestId('company-read-only');
    const name = (await screen.findByLabelText('Legal company name')) as HTMLInputElement;
    expect(name.value).toBe('Hochbau Nord GmbH');
    expect(name.readOnly).toBe(true);
    expect(screen.queryByTestId('company-save')).toBeNull();
    expect(screen.queryByText('Drop your logo here, or click to browse')).toBeNull();
    // What documents print is still shown, since that is what the reader came for.
    expect(screen.getByTestId('letterhead-preview-name')).toHaveTextContent('Hochbau Nord GmbH');
  });

  it('says next to the workspace reset that document types keep their own look', async () => {
    renderPanel();

    const reset = await screen.findByTestId('appearance-reset');
    const note = screen.getByTestId('appearance-reset-note');
    // Beside the button, not somewhere else on the page: the note answers the
    // question the button raises at the moment the admin is about to press it.
    expect(note.parentElement).toBe(reset.parentElement);
    expect(note).toHaveTextContent('Document types with their own look keep it after a reset.');
  });

  it('puts the per-document look under the appearance panel', async () => {
    vi.mocked(templatesApi.getDocumentTypes).mockResolvedValue([
      {
        key: 'rfi',
        label: 'Request for information',
        label_key: 'settings.document_templates.types.rfi',
        fields: ['accent_color'],
        override: {},
        effective: APPEARANCE,
      },
    ]);
    renderPanel();

    const types = await screen.findByTestId('doc-types-panel');
    const appearance = await screen.findByTestId('doc-appearance-panel');
    expect(appearance.compareDocumentPosition(types) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(types).getByText('Request for information')).toBeInTheDocument();
  });
});
