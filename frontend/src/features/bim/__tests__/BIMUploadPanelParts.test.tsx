// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Upload panel regressions: re-uploading the same file silently made a
// duplicate model, rows offered no cancel, and an "Add Model" click made while
// the page was still loading was lost when the page redirected itself from
// /bim to /bim/<model> (the shell remounts the page on every pathname change).

import { useEffect, useState } from 'react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom';

vi.mock('../api', () => ({ findUploadDuplicates: vi.fn() }));

import { useBIMUploadStore, type BIMUploadJob } from '@/stores/useBIMUploadStore';
import {
  BIMUploadDuplicatePrompt,
  BIMUploadJobRow,
  isUploadPanelOpenInNavState,
  uploadPanelNavState,
} from '../BIMUploadPanelParts';

afterEach(() => {
  cleanup();
  useBIMUploadStore.setState({ jobs: new Map() });
});

const pending = (start: (p: string | null) => void) => ({
  fileName: 'tower.rvt',
  duplicates: [{ model_id: 'm-1', name: 'tower', version: '1', status: 'ready', created_at: null }],
  start,
});

describe('BIMUploadDuplicatePrompt', () => {
  it('uploads as a new version of the existing model', () => {
    const start = vi.fn();
    const done = vi.fn();
    render(<BIMUploadDuplicatePrompt pending={pending(start)} onDone={done} />);
    expect(screen.getByTestId('bim-upload-duplicate-prompt').textContent).toContain('tower.rvt');
    fireEvent.click(screen.getByTestId('bim-upload-duplicate-version'));
    expect(start).toHaveBeenCalledWith('m-1');
    expect(done).toHaveBeenCalled();
  });

  it('can still upload as a separate model', () => {
    const start = vi.fn();
    render(<BIMUploadDuplicatePrompt pending={pending(start)} onDone={vi.fn()} />);
    fireEvent.click(screen.getByTestId('bim-upload-duplicate-separate'));
    expect(start).toHaveBeenCalledWith(null);
  });
});

describe('BIMUploadJobRow', () => {
  it('offers cancel while the server converts', () => {
    const cancelUpload = vi.fn();
    useBIMUploadStore.setState({ cancelUpload } as never);
    const job = {
      id: 'j-1',
      fileName: 'tower.rvt',
      status: 'converting',
      stage: 'bim_upload.stage_server_converting',
      progress: 95,
      serverConverting: true,
      startedAt: Date.now(),
      elementCount: 0,
    } as unknown as BIMUploadJob;
    render(<BIMUploadJobRow job={job} />);
    expect(screen.queryByText('95%')).toBeNull();
    fireEvent.click(screen.getByText('Cancel'));
    expect(cancelUpload).toHaveBeenCalledWith('j-1');
  });
});

/** Mimics BIMPage: opens the panel on click and redirects itself once its
 *  model is known, under a shell that remounts per pathname. */
function Page() {
  const location = useLocation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(() => isUploadPanelOpenInNavState(location.state));
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!ready || location.pathname.endsWith('/m-1')) return;
    navigate('/p/bim/m-1', { replace: true, state: uploadPanelNavState(open) });
  }, [ready, open, location.pathname, navigate]);
  return (
    <div>
      <button onClick={() => setOpen(true)}>add</button>
      <button onClick={() => setReady(true)}>loaded</button>
      <span data-testid="path">{location.pathname}</span>
      {open && <span data-testid="panel" />}
    </div>
  );
}

function Shell() {
  const location = useLocation();
  return (
    <Routes key={location.pathname}>
      <Route path="/p/bim" element={<Page />} />
      <Route path="/p/bim/:m" element={<Page />} />
    </Routes>
  );
}

describe('upload panel across the self-redirect', () => {
  it('stays open when the page moves to the model URL', async () => {
    render(
      <MemoryRouter initialEntries={['/p/bim']}>
        <Shell />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByText('add'));
    fireEvent.click(screen.getByText('loaded'));
    await waitFor(() => expect(screen.getByTestId('path').textContent).toBe('/p/bim/m-1'));
    expect(screen.getByTestId('panel')).toBeTruthy();
  });

  it('stays closed when it was not opened', () => {
    expect(isUploadPanelOpenInNavState(uploadPanelNavState(false))).toBe(false);
    expect(isUploadPanelOpenInNavState(null)).toBe(false);
  });
});
