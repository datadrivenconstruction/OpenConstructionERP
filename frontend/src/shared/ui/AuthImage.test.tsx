// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * AuthImage is the one way the platform shows a stored image.
 *
 * Protected API images must be fetched with the bearer token (a bare <img>
 * gets 401 and a broken icon), public URLs must NOT be fetched that way (the
 * token would leak to a third party and the fetch would fail on CORS), and a
 * URL that yields no picture must show the fallback rather than the
 * browser's broken-image icon. The cache is the part that keeps a photo grid
 * from downloading the same thumbnail again on every re-mount.
 */
import { fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useAuthStore } from '@/stores/useAuthStore';
import { AuthImage, isAuthAssetUrl, resetAuthImageCache, useAuthedObjectUrl } from './AuthImage';

const TOKEN = 'test-token';
const fetchMock = vi.fn();
let objectUrls = 0;

beforeEach(() => {
  resetAuthImageCache();
  objectUrls = 0;
  fetchMock.mockReset();
  fetchMock.mockImplementation(async () => new Response(new Blob(['png'], { type: 'image/png' }), { status: 200 }));
  vi.stubGlobal('fetch', fetchMock);
  URL.createObjectURL = vi.fn(() => `blob:test/${++objectUrls}`);
  URL.revokeObjectURL = vi.fn();
  useAuthStore.setState({ accessToken: TOKEN } as never);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('isAuthAssetUrl', () => {
  it('matches our own API paths only', () => {
    expect(isAuthAssetUrl('/api/v1/documents/photos/1/thumb/')).toBe(true);
    expect(isAuthAssetUrl(`${window.location.origin}/api/v1/x`)).toBe(true);
    expect(isAuthAssetUrl('https://seed.local/photos/1.jpg')).toBe(false);
    expect(isAuthAssetUrl('data:image/png;base64,AAAA')).toBe(false);
    expect(isAuthAssetUrl('blob:http://x/1')).toBe(false);
    expect(isAuthAssetUrl('/static/logo.svg')).toBe(false);
    expect(isAuthAssetUrl(null)).toBe(false);
  });
});

describe('AuthImage', () => {
  it('fetches a protected image with the bearer header and shows the object URL', async () => {
    render(<AuthImage src="/api/v1/documents/photos/1/thumb/" alt="slab" />);

    const img = await screen.findByAltText('slab');
    expect(img.getAttribute('src')).toBe('blob:test/1');
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe('/api/v1/documents/photos/1/thumb/');
    expect((init as RequestInit).headers).toMatchObject({ Authorization: `Bearer ${TOKEN}` });
    // The token travels in the header, never in the URL.
    expect(String(url)).not.toContain(TOKEN);
  });

  it('loads a public URL directly and never sends it the token', async () => {
    render(<AuthImage src="https://cdn.example.org/a.jpg" alt="external" />);

    const img = await screen.findByAltText('external');
    expect(img.getAttribute('src')).toBe('https://cdn.example.org/a.jpg');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('shows the fallback when the protected fetch is refused', async () => {
    fetchMock.mockImplementation(async () => new Response('no', { status: 401 }));
    render(<AuthImage src="/api/v1/documents/photos/2/thumb/" alt="x" fallback={<span>no picture</span>} />);

    expect(await screen.findByText('no picture')).toBeTruthy();
    expect(screen.queryByAltText('x')).toBeNull();
  });

  it('shows the fallback instead of a broken icon when a public URL does not load', async () => {
    render(<AuthImage src="https://seed.local/photos/1.jpg" alt="gone" fallback={<span>no picture</span>} />);

    fireEvent.error(await screen.findByAltText('gone'));

    expect(await screen.findByText('no picture')).toBeTruthy();
  });

  it('downloads a thumbnail once for every component showing it', async () => {
    const src = '/api/v1/documents/photos/3/thumb/';
    render(
      <>
        <AuthImage src={src} alt="a" />
        <AuthImage src={src} alt="b" />
      </>,
    );

    await screen.findByAltText('a');
    await screen.findByAltText('b');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('keeps the blob while one reader remains and revokes it after the last', async () => {
    const src = '/api/v1/documents/photos/4/thumb/';
    const first = renderHook(() => useAuthedObjectUrl(src));
    const second = renderHook(() => useAuthedObjectUrl(src));
    await waitFor(() => expect(second.result.current.url).toBe('blob:test/1'));

    first.unmount();
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    second.unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test/1');
  });

  it('retries after a failure instead of caching it', async () => {
    const src = '/api/v1/documents/photos/5/thumb/';
    fetchMock.mockImplementationOnce(async () => new Response('no', { status: 500 }));
    const first = renderHook(() => useAuthedObjectUrl(src));
    await waitFor(() => expect(first.result.current.failed).toBe(true));
    first.unmount();

    const second = renderHook(() => useAuthedObjectUrl(src));
    await waitFor(() => expect(second.result.current.url).toBe('blob:test/1'));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
