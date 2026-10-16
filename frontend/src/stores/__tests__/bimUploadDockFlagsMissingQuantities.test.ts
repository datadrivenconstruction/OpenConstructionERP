// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// An IFC upload converts in the background. When the DDC converter is missing
// the model lands as `degraded` with empty quantities, and the dock used to
// close the job as a plain "Upload complete". It now carries the warning code
// and a stage that says the import came without quantities.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('@/features/bim/api', () => ({
  uploadCADFile: vi.fn(),
  uploadBIMData: vi.fn(),
  generateBIMPDFSheets: vi.fn(),
  fetchBIMModel: vi.fn(),
}));

import * as bimApi from '@/features/bim/api';
import { useBIMUploadStore } from '../useBIMUploadStore';

const upload = vi.mocked(bimApi.uploadCADFile);
const fetchModel = vi.mocked(bimApi.fetchBIMModel);

function start(): string {
  return useBIMUploadStore.getState().startUpload({
    file: new File(['ISO-10303-21;'], 'house.ifc'),
    projectId: 'p-1',
    modelName: 'House',
    discipline: 'architecture',
    uploadType: 'cad',
  });
}

async function settle(jobId: string) {
  for (let i = 0; i < 20; i++) {
    await vi.advanceTimersByTimeAsync(4000);
    if (useBIMUploadStore.getState().jobs.get(jobId)?.status === 'ready') return;
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  upload.mockReset();
  fetchModel.mockReset();
  upload.mockResolvedValue({ model_id: 'm-1', status: 'processing', element_count: 0 } as never);
});

afterEach(() => {
  useBIMUploadStore.setState({ jobs: new Map() });
  vi.useRealTimers();
});

describe('BIM upload dock', () => {
  it('flags a degraded model as imported without quantities', async () => {
    fetchModel.mockResolvedValue({
      id: 'm-1',
      status: 'degraded',
      element_count: 12,
      error_code: 'no_quantities_converter_absent',
    } as never);
    const jobId = start();
    await settle(jobId);
    const job = useBIMUploadStore.getState().jobs.get(jobId)!;
    expect(job.status).toBe('ready');
    expect(job.quantitiesWarning).toBe('no_quantities_converter_absent');
    expect(job.stage).toBe('bim_upload.stage_done_no_quantities');
  });

  it('keeps a ready model a plain success', async () => {
    fetchModel.mockResolvedValue({ id: 'm-1', status: 'ready', element_count: 12 } as never);
    const jobId = start();
    await settle(jobId);
    const job = useBIMUploadStore.getState().jobs.get(jobId)!;
    expect(job.status).toBe('ready');
    expect(job.quantitiesWarning ?? null).toBeNull();
    expect(job.stage).toBe('bim_upload.stage_done');
  });
});
