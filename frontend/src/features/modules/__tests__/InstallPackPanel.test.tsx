// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Tests for <InstallPackPanel /> — the admin-only "Install pack" + "Rescan"
// control strip on the Modules → Partner Packs tab.
//
// Behaviour covered:
//   1. Admin gate: renders nothing for a non-admin user.
//   2. Admin sees the dropzone, the hidden file input and the Rescan button,
//      each with an accessible label.
//   3. Upload success: a valid .zip calls the install mutation, and on success
//      shows a toast naming the pack and calls onChanged (refetch).
//   4. Upload 400: the backend's `detail` string is surfaced verbatim in the
//      error toast (it is already user-safe).
//   5. Client guard: a non-.zip file is rejected before the mutation fires.
//   6. Client guard: a .zip over the 25 MiB cap is rejected before the
//      mutation fires.
//   7. Rescan: clicking Rescan calls the rescan mutation, toasts the count and
//      calls onChanged.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import type { InstallResult } from '../partnerPacks';
import { MAX_PACK_UPLOAD_BYTES } from '../partnerPacks';

/* ── Hook + store mocks ────────────────────────────────────────────────── */

// Partner-pack hooks: install + rescan are controllable per-test. The other
// exports (constants, types) are passed through from the real module.
const packMock = vi.hoisted(() => ({
  useInstallPack: vi.fn(),
  useRescanPacks: vi.fn(),
}));
vi.mock('../partnerPacks', async () => {
  const actual = await vi.importActual<typeof import('../partnerPacks')>('../partnerPacks');
  return { ...actual, ...packMock };
});

// Toast store — capture addToast calls.
const addToast = vi.hoisted(() => vi.fn());
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (selector: (s: { addToast: typeof addToast }) => unknown) =>
    selector({ addToast }),
}));

// Auth store — drive the admin gate via a mutable role.
const authState = vi.hoisted(() => ({ userRole: 'admin' as string | null }));
vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (selector: (s: { userRole: string | null }) => unknown) =>
    selector({ userRole: authState.userRole }),
}));

/* ── Import the component AFTER the mocks are registered ────────────────── */

import { InstallPackPanel } from '../ModulesPage';

/* ── Helpers ───────────────────────────────────────────────────────────── */

function makeInstallMock() {
  const mutate = vi.fn();
  packMock.useInstallPack.mockReturnValue({ mutate, isPending: false });
  return mutate;
}

function makeRescanMock() {
  const mutate = vi.fn();
  packMock.useRescanPacks.mockReturnValue({ mutate, isPending: false });
  return mutate;
}

function renderPanel(onChanged = vi.fn()) {
  const utils = render(
    <MemoryRouter>
      <InstallPackPanel onChanged={onChanged} />
    </MemoryRouter>,
  );
  return { onChanged, ...utils };
}

/** Build a File whose reported size is `bytes` without actually allocating it. */
function fakeFile(name: string, type: string, bytes: number): File {
  const file = new File(['x'], name, { type });
  Object.defineProperty(file, 'size', { value: bytes });
  return file;
}

function fileInput(): HTMLInputElement {
  // The dropzone proxies clicks to a hidden <input type=file>.
  return screen.getByLabelText(/Pack .zip file/i) as HTMLInputElement;
}

/* ── Tests ─────────────────────────────────────────────────────────────── */

beforeEach(() => {
  cleanup();
  addToast.mockReset();
  authState.userRole = 'admin';
  makeInstallMock();
  makeRescanMock();
});

afterEach(() => {
  cleanup();
});

describe('<InstallPackPanel />', () => {
  it('renders nothing for a non-admin user', () => {
    authState.userRole = 'editor';
    const { container } = renderPanel();
    expect(container.firstChild).toBeNull();
  });

  it('renders the dropzone, file input and Rescan button for an admin', () => {
    renderPanel();
    expect(
      screen.getByRole('button', { name: /Upload a pack .zip/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/Pack .zip file/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Rescan packs/i })).toBeInTheDocument();
  });

  it('uploads a valid .zip: calls the install mutation, toasts success, refetches', () => {
    const mutate = makeInstallMock();
    const { onChanged } = renderPanel();

    const file = fakeFile('acme-co.zip', 'application/zip', 4096);
    fireEvent.change(fileInput(), { target: { files: [file] } });

    expect(mutate).toHaveBeenCalledTimes(1);
    const [arg, opts] = mutate.mock.calls[0] as [
      File,
      { onSuccess: (r: InstallResult) => void },
    ];
    expect(arg).toBe(file);

    // Drive the mutation's success callback as React Query would.
    const result: InstallResult = {
      installed: true,
      slug: 'acme-co',
      partner_name: 'ACME Construction',
      pack_version: '0.1.0',
    };
    opts.onSuccess(result);

    // A success toast fires (the test-env i18n mock returns the raw
    // defaultValue without interpolating {{name}}/{{slug}}, so assert on the
    // stable type + title rather than the interpolated message) and the parent
    // is told to refetch.
    expect(addToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'success', title: 'Pack installed' }),
    );
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it('surfaces the backend detail verbatim on a 400 failure', () => {
    const mutate = makeInstallMock();
    renderPanel();

    const file = fakeFile('dup.zip', 'application/zip', 2048);
    fireEvent.change(fileInput(), { target: { files: [file] } });

    const backendDetail = "A pack with slug 'acme-co' is already installed.";
    const [, opts] = mutate.mock.calls[0] as [File, { onError: (e: unknown) => void }];
    opts.onError(new Error(backendDetail));

    expect(addToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error', message: backendDetail }),
    );
  });

  it('rejects a non-.zip file before uploading', () => {
    const mutate = makeInstallMock();
    renderPanel();

    const file = fakeFile('notes.pdf', 'application/pdf', 1024);
    fireEvent.change(fileInput(), { target: { files: [file] } });

    expect(mutate).not.toHaveBeenCalled();
    expect(addToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error', message: expect.stringMatching(/\.zip/i) }),
    );
  });

  it('rejects a .zip over the 25 MiB cap before uploading', () => {
    const mutate = makeInstallMock();
    renderPanel();

    const file = fakeFile('huge.zip', 'application/zip', MAX_PACK_UPLOAD_BYTES + 1);
    fireEvent.change(fileInput(), { target: { files: [file] } });

    expect(mutate).not.toHaveBeenCalled();
    expect(addToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error', message: expect.stringMatching(/25 MB/i) }),
    );
  });

  it('rescans: calls the rescan mutation, toasts the count, refetches', () => {
    const mutate = makeRescanMock();
    const { onChanged } = renderPanel();

    fireEvent.click(screen.getByRole('button', { name: /Rescan packs/i }));
    expect(mutate).toHaveBeenCalledTimes(1);

    const [, opts] = mutate.mock.calls[0] as [
      undefined,
      { onSuccess: (r: { count: number; slugs: string[] }) => void },
    ];
    opts.onSuccess({ count: 3, slugs: ['a', 'b', 'c'] });

    // Success toast + refetch (count is interpolated at runtime; the test-env
    // i18n mock leaves the {{count}} token, so assert on type + title).
    expect(addToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'success', title: 'Rescan complete' }),
    );
    expect(onChanged).toHaveBeenCalledTimes(1);
  });
});
