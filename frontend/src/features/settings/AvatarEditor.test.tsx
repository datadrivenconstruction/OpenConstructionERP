// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Profile photo editor: initials fallback, client-side type and size checks,
 * preview before upload, upload / replace / remove through the API.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const fetchWithAuth = vi.fn();
const apiDelete = vi.fn();
vi.mock('@/shared/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/shared/lib/api')>()),
  fetchWithAuth: (...args: unknown[]) => fetchWithAuth(...args),
  apiDelete: (...args: unknown[]) => apiDelete(...args),
}));
import '@/app/i18n';
import { AvatarEditor } from './AvatarEditor';
import {
  AVATAR_MAX_BYTES,
  avatarErrorKeyForRule,
  validateAvatarFile,
} from './avatarFile';
import { resetAuthImageCache } from '@/shared/ui/AuthImage';

function renderEditor(props: { name?: string; avatarUrl?: string | null }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AvatarEditor name={props.name ?? 'Anna Berg'} avatarUrl={props.avatarUrl ?? null} />
    </QueryClientProvider>,
  );
}

function pick(file: File) {
  fireEvent.change(screen.getByTestId('avatar-input'), { target: { files: [file] } });
}

const png = (size = 1000) => new File([new Uint8Array(size)], 'me.png', { type: 'image/png' });

beforeEach(() => {
  fetchWithAuth.mockReset();
  apiDelete.mockReset();
  resetAuthImageCache();
  URL.createObjectURL = vi.fn(() => 'blob:preview');
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => resetAuthImageCache());

describe('validateAvatarFile', () => {
  it('accepts PNG, JPEG and WebP within the limit', () => {
    for (const type of ['image/png', 'image/jpeg', 'image/webp']) {
      expect(validateAvatarFile({ type, size: 1000 })).toBeNull();
    }
    expect(validateAvatarFile({ type: 'image/png', size: AVATAR_MAX_BYTES })).toBeNull();
  });
  it('refuses other types, oversize and empty files', () => {
    expect(validateAvatarFile({ type: 'image/gif', size: 10 })).toBe('settings.avatar_err_type');
    expect(validateAvatarFile({ type: 'image/svg+xml', size: 10 })).toBe('settings.avatar_err_type');
    expect(validateAvatarFile({ type: '', size: 10 })).toBe('settings.avatar_err_type');
    expect(validateAvatarFile({ type: 'image/png', size: AVATAR_MAX_BYTES + 1 })).toBe('settings.avatar_err_size');
    expect(validateAvatarFile({ type: 'image/png', size: 0 })).toBe('settings.avatar_err_content');
  });
  it('maps server rule ids to message keys', () => {
    expect(avatarErrorKeyForRule('users.avatar.type')).toBe('settings.avatar_err_type');
    expect(avatarErrorKeyForRule('users.avatar.size')).toBe('settings.avatar_err_size');
    expect(avatarErrorKeyForRule('users.avatar.content')).toBe('settings.avatar_err_content');
    expect(avatarErrorKeyForRule(undefined)).toBe('settings.avatar_err_content');
  });
});

describe('AvatarEditor', () => {
  it('shows the initial and only an Upload action when there is no photo', () => {
    renderEditor({ name: 'anna berg' });
    expect(screen.getByText('A')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Upload photo/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Remove photo/ })).toBeNull();
  });

  it('offers Change and Remove when a photo exists', () => {
    renderEditor({ avatarUrl: '/api/v1/users/me/avatar/?v=abc' });
    expect(screen.getByRole('button', { name: /Change photo/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Remove photo/ })).toBeInTheDocument();
  });

  it('rejects a wrong type or oversize file without calling the API', () => {
    renderEditor({});
    pick(new File(['x'], 'a.gif', { type: 'image/gif' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Choose a PNG, JPEG or WebP image.');
    pick(png(AVATAR_MAX_BYTES + 1));
    expect(screen.getByRole('alert')).toHaveTextContent('larger than 2 MB');
    expect(screen.queryByTestId('avatar-preview')).toBeNull();
    expect(fetchWithAuth).not.toHaveBeenCalled();
  });

  it('previews a valid file first and uploads only on Save', async () => {
    fetchWithAuth.mockResolvedValue({ ok: true, status: 200 });
    renderEditor({});
    pick(png());
    expect(screen.getByTestId('avatar-preview')).toBeInTheDocument();
    expect(fetchWithAuth).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /Save photo/ }));
    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(1));
    const [url, init] = fetchWithAuth.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/users/me/avatar/');
    expect(init.method).toBe('POST');
    expect((init.body as FormData).get('file')).toBeInstanceOf(File);
    await waitFor(() => expect(screen.queryByTestId('avatar-preview')).toBeNull());
  });

  it('Cancel drops the pending file without uploading', () => {
    renderEditor({});
    pick(png());
    fireEvent.click(screen.getByRole('button', { name: /Cancel/ }));
    expect(screen.queryByTestId('avatar-preview')).toBeNull();
    expect(fetchWithAuth).not.toHaveBeenCalled();
  });

  it('shows the server rule message when the upload is refused with 422', async () => {
    fetchWithAuth.mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: { rule: 'users.avatar.content', message: 'x' } }),
    });
    renderEditor({});
    pick(png());
    fireEvent.click(screen.getByRole('button', { name: /Save photo/ }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('not a readable image'));
  });

  it('removes the photo through DELETE', async () => {
    apiDelete.mockResolvedValue({});
    renderEditor({ avatarUrl: '/api/v1/users/me/avatar/?v=abc' });
    fireEvent.click(screen.getByRole('button', { name: /Remove photo/ }));
    await waitFor(() => expect(apiDelete).toHaveBeenCalledWith('/v1/users/me/avatar/'));
  });
});
