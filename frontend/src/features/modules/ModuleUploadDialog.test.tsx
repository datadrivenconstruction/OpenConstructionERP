import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import JSZip from 'jszip';
import { ModuleUploadDialog } from './ModuleUploadDialog';
import { useModuleStore } from '@/stores/useModuleStore';

/* ── Helpers ───────────────────────────────────────────────────────────── */

/** Build a File object from a JSZip instance. */
async function buildZipFile(
  zip: JSZip,
  name = 'my-module.zip',
): Promise<File> {
  const blob = await zip.generateAsync({ type: 'blob' });
  return new File([blob], name, { type: 'application/zip' });
}

/** Create a valid manifest object. */
function validManifest(overrides: Record<string, unknown> = {}) {
  return {
    name: 'oe-test-module',
    version: '1.0.0',
    displayName: 'Test Module',
    description: 'A test module for unit tests.',
    author: 'Test Author',
    category: 'tools',
    ...overrides,
  };
}

/** Create a zip File with a manifest.json inside. */
async function buildModuleZip(
  manifest: Record<string, unknown> = validManifest(),
  fileName = 'my-module.zip',
): Promise<File> {
  const zip = new JSZip();
  zip.file('manifest.json', JSON.stringify(manifest));
  return buildZipFile(zip, fileName);
}

function renderDialog(open = true, onClose = vi.fn()) {
  return render(<ModuleUploadDialog open={open} onClose={onClose} />);
}

/* ── Tests ─────────────────────────────────────────────────────────────── */

describe('ModuleUploadDialog', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // Reset custom modules in the store
    useModuleStore.setState({ customModules: [] });
    localStorage.clear();
  });

  it('does not render when open=false', () => {
    renderDialog(false);
    expect(screen.queryByText('Upload Module')).not.toBeInTheDocument();
  });

  it('renders the dialog when open=true', () => {
    renderDialog(true);
    expect(screen.getByText('Upload Module')).toBeInTheDocument();
    expect(
      screen.getByText('Drag & drop a .zip file or click to browse'),
    ).toBeInTheDocument();
  });

  it('calls onClose when close button is clicked', () => {
    const onClose = vi.fn();
    renderDialog(true, onClose);
    fireEvent.click(screen.getByTestId('upload-dialog-close'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose on Escape key', () => {
    const onClose = vi.fn();
    renderDialog(true, onClose);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('rejects non-zip files with an error message', async () => {
    renderDialog();
    const fileInput = screen.getByTestId('upload-file-input') as HTMLInputElement;

    const textFile = new File(['hello'], 'readme.txt', {
      type: 'text/plain',
    });

    // Use fireEvent.change directly because userEvent.upload respects
    // the accept attribute and may silently skip non-matching files.
    fireEvent.change(fileInput, { target: { files: [textFile] } });

    await waitFor(() => {
      expect(screen.getByTestId('upload-error')).toBeInTheDocument();
    });
    expect(
      screen.getByText(/Only .zip files are accepted/),
    ).toBeInTheDocument();
  });

  it('rejects a zip without manifest.json', async () => {
    const zip = new JSZip();
    zip.file('readme.txt', 'no manifest here');
    const file = await buildZipFile(zip);

    renderDialog();
    const fileInput = screen.getByTestId('upload-file-input');
    await userEvent.upload(fileInput, file);

    await waitFor(() => {
      expect(screen.getByTestId('upload-error')).toBeInTheDocument();
    });
    expect(
      screen.getByText(/No manifest.json found/),
    ).toBeInTheDocument();
  });

  it('rejects a zip with invalid JSON in manifest.json', async () => {
    const zip = new JSZip();
    zip.file('manifest.json', '{ broken json !!!');
    const file = await buildZipFile(zip);

    renderDialog();
    const fileInput = screen.getByTestId('upload-file-input');
    await userEvent.upload(fileInput, file);

    await waitFor(() => {
      expect(screen.getByTestId('upload-error')).toBeInTheDocument();
    });
    expect(
      screen.getByText(/manifest.json contains invalid JSON/),
    ).toBeInTheDocument();
  });

  it('rejects a manifest missing required fields', async () => {
    const file = await buildModuleZip({ name: 'test' }); // missing version, displayName

    renderDialog();
    const fileInput = screen.getByTestId('upload-file-input');
    await userEvent.upload(fileInput, file);

    await waitFor(() => {
      expect(screen.getByTestId('upload-error')).toBeInTheDocument();
    });
    expect(
      screen.getByText(/missing required field "version"/),
    ).toBeInTheDocument();
  });

  it('shows module preview for a valid zip', async () => {
    const manifest = validManifest();
    const file = await buildModuleZip(manifest);

    renderDialog();
    const fileInput = screen.getByTestId('upload-file-input');
    await userEvent.upload(fileInput, file);

    await waitFor(() => {
      expect(screen.getByTestId('upload-preview')).toBeInTheDocument();
    });
    expect(screen.getByText('Test Module')).toBeInTheDocument();
    expect(screen.getByText(/oe-test-module v1.0.0/)).toBeInTheDocument();
    expect(
      screen.getByText('A test module for unit tests.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Test Author')).toBeInTheDocument();
  });

  it('installs the module when Install button is clicked', async () => {
    const onClose = vi.fn();
    const manifest = validManifest();
    const file = await buildModuleZip(manifest);

    render(<ModuleUploadDialog open={true} onClose={onClose} />);
    const fileInput = screen.getByTestId('upload-file-input');
    await userEvent.upload(fileInput, file);

    await waitFor(() => {
      expect(screen.getByTestId('upload-install-btn')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('upload-install-btn'));

    // Verify module was added to the store
    const { customModules } = useModuleStore.getState();
    expect(customModules).toHaveLength(1);
    expect(customModules[0]!.name).toBe('oe-test-module');
    expect(customModules[0]!.version).toBe('1.0.0');
    expect(customModules[0]!.displayName).toBe('Test Module');

    // Dialog should close
    expect(onClose).toHaveBeenCalled();
  });

  it('rejects installing a module with a duplicate name', async () => {
    // Pre-install a module
    useModuleStore.getState().installCustomModule({
      name: 'oe-test-module',
      version: '1.0.0',
      displayName: 'Test Module',
    });

    const file = await buildModuleZip(validManifest());

    renderDialog();
    const fileInput = screen.getByTestId('upload-file-input');
    await userEvent.upload(fileInput, file);

    await waitFor(() => {
      expect(screen.getByTestId('upload-error')).toBeInTheDocument();
    });
    expect(
      screen.getByText(/already installed/),
    ).toBeInTheDocument();
  });

  it('finds manifest.json one directory level deep', async () => {
    const zip = new JSZip();
    zip.file(
      'my-module/manifest.json',
      JSON.stringify(validManifest({ displayName: 'Nested Module' })),
    );
    const file = await buildZipFile(zip);

    renderDialog();
    const fileInput = screen.getByTestId('upload-file-input');
    await userEvent.upload(fileInput, file);

    await waitFor(() => {
      expect(screen.getByTestId('upload-preview')).toBeInTheDocument();
    });
    expect(screen.getByText('Nested Module')).toBeInTheDocument();
  });
});
