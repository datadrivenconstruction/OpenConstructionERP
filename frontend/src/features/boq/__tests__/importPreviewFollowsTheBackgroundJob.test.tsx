// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The import preview follows the background job the server imports in.
//
// A large bill took longer than the dialog waited for an answer; the server
// went on writing, and the user's retry imported the bill a second time. The
// dialog now asks for a background import, shows the job's progress while it
// runs, and reports the result once the job ends, the same way as before.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';

import { ImportPreviewDialog } from '../ImportPreviewDialog';
import { useToastStore } from '@/stores/useToastStore';

const PREVIEW = {
  positions: [
    {
      ordinal: '1.1.1',
      code: 'EX26_01.A00.001.001',
      description: 'Muratura in blocchi',
      unit: 'mq',
      quantity: 49.11,
      unit_rate: 13.63,
      total: 669.37,
      is_section: false,
      classification: {},
      metadata: {},
    },
  ],
  total_positions: 1,
  total_sections: 0,
  currency: 'EUR',
  source_format: 'xpwe',
  warnings: [],
  errors: [],
  skipped: 0,
  truncated: false,
  metadata: {},
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useToastStore.setState({ toasts: [] });
});

async function confirmImport(onImported: () => void = () => {}) {
  render(<ImportPreviewDialog open onClose={() => {}} boqId="boq-1" onImported={onImported} />);
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(['x'], 'computo.xpwe')] } });
  const next = await screen.findByRole('button', { name: 'Continue' });
  await waitFor(() => expect(next).not.toBeDisabled());
  fireEvent.click(next);
  fireEvent.click(await screen.findByRole('button', { name: 'Import' }));
}

describe('import preview background job', () => {
  it('shows the progress of the job and reports its result when it ends', async () => {
    const onImported = vi.fn();
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json(PREVIEW))
      .mockResolvedValueOnce(json({ job_id: 'job-1', status: 'pending', progress_percent: 0, reused: false }, 202))
      .mockResolvedValueOnce(json({ job_id: 'job-1', status: 'started', progress_percent: 40, phase: 'writing' }))
      .mockResolvedValueOnce(
        json({
          job_id: 'job-1',
          status: 'success',
          progress_percent: 100,
          phase: 'validating',
          result: { imported: 11, created: 11, warnings: [] },
        }),
      );
    await confirmImport(onImported);

    expect(await screen.findByText(/Writing the positions… 40%/)).toBeInTheDocument();
    await waitFor(() => expect(onImported).toHaveBeenCalled(), { timeout: 5000 });

    const urls = fetchSpy.mock.calls.map(([url]) => String(url));
    expect(urls[1]).toBe('/api/v1/boq/boqs/boq-1/import/auto/?background=true');
    expect(urls.slice(2)).toEqual(['/api/v1/boq/boqs/boq-1/import/jobs/job-1/', '/api/v1/boq/boqs/boq-1/import/jobs/job-1/']);
    expect(useToastStore.getState().toasts.map((toast) => toast.title)).toContain('Imported 11 positions');
  });

  it("shows the server's reason when the job refused the file", async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json(PREVIEW))
      .mockResolvedValueOnce(json({ job_id: 'job-2', status: 'pending', progress_percent: 0 }, 202))
      .mockResolvedValueOnce(
        json({ job_id: 'job-2', status: 'failed', progress_percent: 5, error: 'Could not parse file as XPWE: not a bill' }),
      );
    await confirmImport();

    expect(await screen.findByText('Could not parse file as XPWE: not a bill')).toBeInTheDocument();
    expect(useToastStore.getState().toasts.map((toast) => toast.type)).toContain('error');
  });

  it('says a file was imported before and imports it again only when asked', async () => {
    const onImported = vi.fn();
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json(PREVIEW))
      .mockResolvedValueOnce(
        json(
          {
            detail: {
              code: 'import_already_done',
              params: { imported_at: '2026-10-01T09:30:00+00:00', job_id: 'job-0' },
              message: 'This file was already imported into this bill on 2026-10-01T09:30:00+00:00.',
            },
          },
          409,
        ),
      )
      .mockResolvedValueOnce(json({ imported: 11, created: 11, warnings: [] }));
    await confirmImport(onImported);

    expect(await screen.findByText(/already imported into this bill/)).toBeInTheDocument();
    expect(onImported).not.toHaveBeenCalled();
    expect(useToastStore.getState().toasts.map((toast) => toast.type)).not.toContain('error');

    fireEvent.click(screen.getByRole('button', { name: 'Import again' }));
    await waitFor(() => expect(onImported).toHaveBeenCalled());
    const urls = fetchSpy.mock.calls.map(([url]) => String(url));
    expect(urls[1]).toBe('/api/v1/boq/boqs/boq-1/import/auto/?background=true');
    expect(urls[2]).toBe('/api/v1/boq/boqs/boq-1/import/auto/?background=true&force=true');
  });

  it('reads a synchronous answer as before', async () => {
    const onImported = vi.fn();
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json(PREVIEW))
      .mockResolvedValueOnce(json({ imported: 4, warnings: [], method: 'smart_fallback' }));
    await confirmImport(onImported);

    await waitFor(() => expect(onImported).toHaveBeenCalled());
    expect(useToastStore.getState().toasts.map((toast) => toast.title)).toContain('Imported 4 positions');
  });
});
