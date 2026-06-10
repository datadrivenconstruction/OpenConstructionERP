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

  it('uploads large BIM files as resumable chunks', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    const fileSize = 9 * 1024 * 1024 + 1;
    const initResponse = {
      model_id: 'model-1',
      project_id: 'project-1',
      upload_id: 'upload-1',
      key: 'projects/project-1/models/model-1/original.ifc',
      filename: 'big.ifc',
      file_size: fileSize,
      chunk_size_bytes: 8 * 1024 * 1024,
      model_format: 'ifc',
      name: 'Big model',
      discipline: 'architecture',
      conversion_depth: 'standard',
      status: 'uploading',
      uploaded_bytes: 0,
      next_part_number: 1,
      uploaded_parts: [],
    };
    const firstChunk = 8 * 1024 * 1024;
    const finalResponse = {
      model_id: 'model-1',
      name: 'Big model',
      format: 'ifc',
      file_size: fileSize,
      status: 'processing',
      element_count: 0,
    };

    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify(initResponse), {
          status: 201,
          headers: { 'content-type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            model_id: 'model-1',
            part_number: 1,
            etag: 'etag-1',
            size_bytes: firstChunk,
            uploaded_bytes: firstChunk,
            next_part_number: 2,
            complete: false,
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            model_id: 'model-1',
            part_number: 2,
            etag: 'etag-2',
            size_bytes: fileSize - firstChunk,
            uploaded_bytes: fileSize,
            next_part_number: 3,
            complete: false,
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(finalResponse), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      );

    const file = new File([new Uint8Array(fileSize)], 'big.ifc');
    const result = await uploadCADFile('project-1', 'Big model', 'architecture', file);

    expect(result).toEqual(finalResponse);
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(String(fetchMock.mock.calls[0][0])).toContain('/upload-cad/resumable/');
    expect(String(fetchMock.mock.calls[1][0])).toContain('/upload/parts/1/');
    expect(String(fetchMock.mock.calls[2][0])).toContain('/upload/parts/2/');
    expect(String(fetchMock.mock.calls[3][0])).toContain('/upload/complete/');
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
