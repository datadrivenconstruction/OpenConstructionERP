// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Tests for the two chips added to the project header block:
 *
 *   ProjectJobNumberChip — the job number every register reference is minted
 *                          from, settable and changeable in place.
 *   ProjectProposalChip  — the original proposal: attach when there is none,
 *                          a chip that opens a viewer when there is one.
 *
 * Both are extracted from ProjectDetailPage precisely so they can be tested
 * without mounting the 3,000-line hub.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ProjectJobNumberChip } from '../components/ProjectJobNumberChip';
import {
  ProjectProposalChip,
  readProposal,
  formatBytes,
  MAX_PROPOSAL_BYTES,
} from '../components/ProjectProposalChip';

/* ── Mocks ────────────────────────────────────────────────────────────── */

const ask = vi.fn();
vi.mock('@/shared/ui/askDialog', () => ({ ask: (...args: unknown[]) => ask(...args) }));

const apiPatch = vi.fn();
vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: (path: string, body: unknown) => apiPatch(path, body),
  apiDelete: vi.fn(),
}));

const fetchProtectedObjectUrl = vi.fn();
const downloadProtectedFile = vi.fn();
vi.mock('@/features/file-manager/api', () => ({
  fetchProtectedObjectUrl: (url: string) => fetchProtectedObjectUrl(url),
  downloadProtectedFile: (url: string, name: string) => downloadProtectedFile(url, name),
}));

function withClient(node: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  fetchProtectedObjectUrl.mockResolvedValue('blob:proposal');
  apiPatch.mockResolvedValue({});
});

/* ── Job number ───────────────────────────────────────────────────────── */

describe('ProjectJobNumberChip', () => {
  it('renders the code as a monospace chip', () => {
    withClient(<ProjectJobNumberChip code="40118" onChange={vi.fn()} />);
    const chip = screen.getByTestId('project-job-chip');
    expect(chip.textContent).toContain('Job');
    expect(chip.textContent).toContain('40118');
    expect(chip.querySelector('.font-mono')?.textContent).toBe('40118');
  });

  it('offers a set action when the job number is missing', () => {
    withClient(<ProjectJobNumberChip code={null} onChange={vi.fn()} />);
    expect(screen.getByTestId('project-job-chip-set')).toHaveTextContent(
      'Set the job number',
    );
    expect(screen.queryByTestId('project-job-chip')).toBeNull();
  });

  it('reports the new code when the editor is confirmed', async () => {
    ask.mockResolvedValue(['40119']);
    const onChange = vi.fn();
    withClient(<ProjectJobNumberChip code="40118" onChange={onChange} />);
    fireEvent.click(screen.getByTestId('project-job-chip-edit'));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith('40119'));
  });

  it('right-clicking the chip opens the same editor', async () => {
    ask.mockResolvedValue(['40120']);
    const onChange = vi.fn();
    withClient(<ProjectJobNumberChip code="40118" onChange={onChange} />);
    fireEvent.contextMenu(screen.getByTestId('project-job-chip'));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith('40120'));
  });

  it('does not fire an update when the value is unchanged or cancelled', async () => {
    const onChange = vi.fn();
    ask.mockResolvedValue(['40118']);
    withClient(<ProjectJobNumberChip code="40118" onChange={onChange} />);
    fireEvent.click(screen.getByTestId('project-job-chip-edit'));
    await waitFor(() => expect(ask).toHaveBeenCalled());
    ask.mockResolvedValue(null);
    fireEvent.click(screen.getByTestId('project-job-chip-edit'));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('hides the editor entirely in read-only mode', () => {
    withClient(
      <ProjectJobNumberChip code="40118" onChange={vi.fn()} canManage={false} />,
    );
    expect(screen.getByTestId('project-job-chip')).toBeInTheDocument();
    expect(screen.queryByTestId('project-job-chip-edit')).toBeNull();
  });
});

/* ── Proposal ─────────────────────────────────────────────────────────── */

const PDF_PROPOSAL = {
  file_id: 'doc-1',
  filename: 'Original proposal.pdf',
  content_type: 'application/pdf',
  size: 482_000,
  uploaded_at: '2026-08-14T02:11:00Z',
  uploaded_by: 'sample.user',
};

describe('ProjectProposalChip', () => {
  it('shows the attach action when nothing is attached', () => {
    withClient(<ProjectProposalChip projectId="p1" metadata={{}} />);
    expect(screen.getByTestId('proposal-attach')).toHaveTextContent(
      'Attach the original proposal',
    );
    expect(screen.queryByTestId('proposal-chip')).toBeNull();
  });

  it('hides the attach action from someone who cannot manage the project', () => {
    withClient(
      <ProjectProposalChip projectId="p1" metadata={{}} canManage={false} />,
    );
    expect(screen.queryByTestId('proposal-attach')).toBeNull();
  });

  it('renders the filename as a chip, with size and date in the tooltip', () => {
    withClient(
      <ProjectProposalChip projectId="p1" metadata={{ proposal: PDF_PROPOSAL }} />,
    );
    const chip = screen.getByTestId('proposal-chip');
    expect(chip).toHaveTextContent('Original proposal.pdf');
    expect(chip.getAttribute('title')).toContain('471 KB');
    expect(chip.getAttribute('title')).toContain('2026-08-14');
  });

  it('opens the PDF viewer popup when the chip is clicked', async () => {
    withClient(
      <ProjectProposalChip projectId="p1" metadata={{ proposal: PDF_PROPOSAL }} />,
    );
    fireEvent.click(screen.getByTestId('proposal-chip'));
    // The shared InlinePdfPreviewModal is reused rather than a second viewer.
    expect(await screen.findByTestId('inline-pdf-preview')).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchProtectedObjectUrl).toHaveBeenCalledWith(
        '/api/v1/documents/doc-1/download',
      ),
    );
  });

  it('shows an inline image for an image proposal', async () => {
    withClient(
      <ProjectProposalChip
        projectId="p1"
        metadata={{
          proposal: { ...PDF_PROPOSAL, filename: 'proposal.png', content_type: 'image/png' },
        }}
      />,
    );
    fireEvent.click(screen.getByTestId('proposal-chip'));
    expect(await screen.findByTestId('proposal-viewer-image')).toHaveAttribute(
      'src',
      'blob:proposal',
    );
  });

  it('states the type and offers a download for a format it cannot show', async () => {
    withClient(
      <ProjectProposalChip
        projectId="p1"
        metadata={{
          proposal: {
            ...PDF_PROPOSAL,
            filename: 'proposal.docx',
            content_type:
              'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          },
        }}
      />,
    );
    fireEvent.click(screen.getByTestId('proposal-chip'));
    expect(await screen.findByTestId('proposal-viewer-note')).toHaveTextContent(
      /cannot be shown inline/i,
    );
    expect(screen.getByTestId('proposal-viewer-download')).toBeInTheDocument();
  });

  it('closes the viewer on Escape', async () => {
    withClient(
      <ProjectProposalChip
        projectId="p1"
        metadata={{ proposal: { ...PDF_PROPOSAL, filename: 'proposal.png', content_type: 'image/png' } }}
      />,
    );
    fireEvent.click(screen.getByTestId('proposal-chip'));
    await screen.findByTestId('proposal-viewer');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByTestId('proposal-viewer')).toBeNull();
  });

  it('right-click offers open / download / replace / remove', async () => {
    withClient(
      <ProjectProposalChip projectId="p1" metadata={{ proposal: PDF_PROPOSAL }} />,
    );
    fireEvent.contextMenu(screen.getByTestId('proposal-chip'));
    const menu = screen.getByTestId('proposal-menu');
    expect(menu).toHaveTextContent('Open');
    expect(menu).toHaveTextContent('Download');
    expect(menu).toHaveTextContent('Replace');
    expect(menu).toHaveTextContent('Remove');
  });

  it('removing clears only the pointer, via a metadata PATCH', async () => {
    withClient(
      <ProjectProposalChip projectId="p1" metadata={{ proposal: PDF_PROPOSAL }} />,
    );
    fireEvent.contextMenu(screen.getByTestId('proposal-chip'));
    fireEvent.click(screen.getByTestId('proposal-menu-remove'));
    await waitFor(() =>
      expect(apiPatch).toHaveBeenCalledWith('/v1/projects/p1', {
        metadata: { proposal: null },
      }),
    );
  });

  it('refuses a file type the slot does not accept, without uploading', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    withClient(<ProjectProposalChip projectId="p1" metadata={{}} />);
    const input = screen.getByTestId('proposal-file-input') as HTMLInputElement;
    const file = new File(['x'], 'notes.exe', { type: 'application/octet-stream' });
    fireEvent.change(input, { target: { files: [file] } });
    expect(await screen.findByTestId('proposal-error')).toHaveTextContent(
      /PDF, Word document or image/i,
    );
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it('refuses an oversized file with an honest message', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    withClient(<ProjectProposalChip projectId="p1" metadata={{}} />);
    const input = screen.getByTestId('proposal-file-input') as HTMLInputElement;
    const file = new File(['x'], 'huge.pdf', { type: 'application/pdf' });
    Object.defineProperty(file, 'size', { value: MAX_PROPOSAL_BYTES + 1 });
    fireEvent.change(input, { target: { files: [file] } });
    expect(await screen.findByTestId('proposal-error')).toHaveTextContent(
      /capped at 40\.0 MB/i,
    );
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});

describe('proposal helpers', () => {
  it('readProposal ignores junk metadata rather than rendering a broken chip', () => {
    expect(readProposal(undefined)).toBeNull();
    expect(readProposal({})).toBeNull();
    expect(readProposal({ proposal: 'not-an-object' })).toBeNull();
    expect(readProposal({ proposal: { filename: 'no-id.pdf' } })).toBeNull();
    expect(readProposal({ proposal: PDF_PROPOSAL })?.file_id).toBe('doc-1');
  });

  it('formatBytes reads in the unit a human would use', () => {
    expect(formatBytes(0)).toBe('—');
    expect(formatBytes(900)).toBe('900 B');
    expect(formatBytes(482_000)).toBe('471 KB');
    expect(formatBytes(5_242_880)).toBe('5.0 MB');
  });
});
