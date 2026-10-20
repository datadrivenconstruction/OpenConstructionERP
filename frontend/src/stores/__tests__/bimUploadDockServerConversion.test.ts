// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A CAD upload returns at once and converts on the server. The dock used to
// (a) keep a lost progress timer alive that pushed a finished job back to
// "Finalizing model setup..." at 71-95%, (b) let a slow status poll raise the
// global "request took too long" toast as if the upload had failed, and
// (c) offer no way to stop a server conversion.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('@/features/bim/api', () => ({
  uploadCADFile: vi.fn(),
  uploadBIMData: vi.fn(),
  generateBIMPDFSheets: vi.fn(),
  fetchBIMModel: vi.fn(),
  deleteBIMModel: vi.fn(),
}));

import * as bimApi from '@/features/bim/api';
import { useBIMUploadStore } from '../useBIMUploadStore';

const upload = vi.mocked(bimApi.uploadCADFile);
const fetchModel = vi.mocked(bimApi.fetchBIMModel);
const deleteModel = vi.mocked(bimApi.deleteBIMModel);

function start(): string {
  return useBIMUploadStore.getState().startUpload({
    file: new File(['RVT'], 'tower.rvt'),
    projectId: 'p-1',
    modelName: 'Tower',
    discipline: 'architecture',
    uploadType: 'cad',
  });
}

const job = (id: string) => useBIMUploadStore.getState().jobs.get(id);

beforeEach(() => {
  vi.useFakeTimers();
  upload.mockReset();
  fetchModel.mockReset();
  deleteModel.mockReset();
  deleteModel.mockResolvedValue(undefined);
});

afterEach(() => {
  useBIMUploadStore.setState({ jobs: new Map() });
  vi.useRealTimers();
});

describe('BIM upload dock, server-side conversion', () => {
  it('stays ready once the model is ready, even after the progress timer would have run on', async () => {
    // The upload answers only after the simulated stages moved past phase 0,
    // which is when the old code lost the live interval handle.
    upload.mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve({ model_id: 'm-1', status: 'processing', element_count: 0 } as never), 6000)),
    );
    fetchModel.mockResolvedValue({ id: 'm-1', status: 'ready', element_count: 534 } as never);
    const id = start();
    await vi.advanceTimersByTimeAsync(6000);
    await vi.advanceTimersByTimeAsync(4000);
    expect(job(id)?.status).toBe('ready');
    await vi.advanceTimersByTimeAsync(60_000);
    expect(job(id)?.status).toBe('ready');
    expect(job(id)?.progress).toBe(100);
    expect(job(id)?.stage).toBe('bim_upload.stage_done');
  });

  it('shows a server-converting state and polls without the global timeout toast', async () => {
    upload.mockResolvedValue({ model_id: 'm-1', status: 'processing', element_count: 0 } as never);
    fetchModel.mockResolvedValue({ id: 'm-1', status: 'processing', element_count: 0 } as never);
    const id = start();
    await vi.advanceTimersByTimeAsync(4000);
    expect(job(id)?.status).toBe('converting');
    expect(job(id)?.serverConverting).toBe(true);
    expect(job(id)?.stage).toBe('bim_upload.stage_server_converting');
    expect(fetchModel).toHaveBeenCalledWith('m-1', { suppressTimeoutToast: true });
  });

  it('keeps waiting when a poll times out', async () => {
    upload.mockResolvedValue({ model_id: 'm-1', status: 'processing', element_count: 0 } as never);
    const timeout = Object.assign(new Error('The request took too long and was cancelled.'), { isTimeout: true });
    fetchModel
      .mockRejectedValueOnce(timeout)
      .mockResolvedValue({ id: 'm-1', status: 'ready', element_count: 5665 } as never);
    const id = start();
    await vi.advanceTimersByTimeAsync(4000);
    expect(job(id)?.status).toBe('converting');
    expect(job(id)?.errorMessage).toBeNull();
    await vi.advanceTimersByTimeAsync(4000);
    expect(job(id)?.status).toBe('ready');
    expect(job(id)?.elementCount).toBe(5665);
  });

  it('cancel during server conversion deletes the server model and stops polling', async () => {
    upload.mockResolvedValue({ model_id: 'm-1', status: 'processing', element_count: 0 } as never);
    fetchModel.mockResolvedValue({ id: 'm-1', status: 'processing', element_count: 0 } as never);
    const id = start();
    await vi.advanceTimersByTimeAsync(4000);
    useBIMUploadStore.getState().cancelUpload(id);
    expect(deleteModel).toHaveBeenCalledWith('m-1');
    expect(job(id)).toBeUndefined();
    const calls = fetchModel.mock.calls.length;
    await vi.advanceTimersByTimeAsync(20_000);
    expect(fetchModel.mock.calls.length).toBe(calls);
  });

  it('drops the job when the server model is gone', async () => {
    upload.mockResolvedValue({ model_id: 'm-1', status: 'processing', element_count: 0 } as never);
    fetchModel.mockRejectedValue(Object.assign(new Error('Not found'), { status: 404 }));
    const id = start();
    await vi.advanceTimersByTimeAsync(4000);
    expect(job(id)).toBeUndefined();
  });
});
