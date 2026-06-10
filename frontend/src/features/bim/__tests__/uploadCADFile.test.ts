import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: {
    getState: () => ({ accessToken: 'test-token' }),
  },
}));

import { uploadCADFile } from '../api';

describe('uploadCADFile', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('shows a clearer message when the upload is rejected with HTTP 413', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('', { status: 413, statusText: 'Payload Too Large' }),
    );

    await expect(
      uploadCADFile('project-1', 'Model', 'architecture', new File(['ifc'], 'model.ifc')),
    ).rejects.toThrow('The file is too large. Please try a smaller one.');

    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('explains that a network-style failure may be a proxy body-size block', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'));

    await expect(
      uploadCADFile('project-1', 'Model', 'architecture', new File(['ifc'], 'model.ifc')),
    ).rejects.toThrow(
      'Upload failed before it reached the server. If this is a very large file, a proxy in front of the app may be blocking it.',
    );
  });
});
