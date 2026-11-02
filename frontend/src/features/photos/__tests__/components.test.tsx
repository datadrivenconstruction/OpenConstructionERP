import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';

vi.mock('@/shared/ui/AuthImage', () => ({
  AuthImage: ({ alt }: { alt?: string }) => <img alt={alt ?? ''} />,
  isAuthAssetUrl: () => true,
  useAuthedObjectUrl: () => ({ url: null, failed: false }),
  resetAuthImageCache: () => undefined,
}));

vi.mock('../api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../api')>();
  return {
    ...real,
    fetchByTarget: vi.fn(),
    fetchSuggestions: vi.fn(),
    acceptSuggestion: vi.fn(),
    rejectSuggestion: vi.fn(),
    analyzePhoto: vi.fn(),
  };
});

import * as api from '../api';
import type { ArchivePhoto, Suggestion } from '../api';
import { PhotoStrip } from '../components/PhotoStrip';
import { BeforeAfterSlider } from '../components/BeforeAfterSlider';
import { AISuggestionList } from '../components/AISuggestionList';

function photo(id: string, extra: Partial<ArchivePhoto> = {}): ArchivePhoto {
  return {
    id,
    project_id: 'proj',
    filename: `${id}.jpg`,
    caption: `Caption ${id}`,
    category: 'site',
    tags: [],
    taken_at: '2026-10-01T09:00:00Z',
    created_at: '2026-10-01T09:00:00Z',
    created_by: 'u',
    gps_lat: null,
    gps_lon: null,
    gps_accuracy_m: null,
    width: 10,
    height: 10,
    sha256: null,
    source_module: 'documents',
    source_id: null,
    thumb_status: 'ready',
    location_id: null,
    zone: null,
    is_archived: false,
    evidence_grade: 'none',
    taken_at_source: null,
    file_url: `/api/v1/photos/${id}/file/`,
    thumb_url: `/api/v1/photos/${id}/thumb/`,
    links: [],
    ...extra,
  };
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe('PhotoStrip', () => {
  it('asks the archive for the photos of one record and shows them', async () => {
    vi.mocked(api.fetchByTarget).mockResolvedValue([photo('a'), photo('b')]);
    wrap(<PhotoStrip projectId="proj" kind="boq_position" targetId="pos-1" canUpload={false} />);
    expect(await screen.findByRole('button', { name: 'Caption a' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Caption b' })).toBeTruthy();
    expect(api.fetchByTarget).toHaveBeenCalledWith('proj', 'boq_position', 'pos-1');
  });

  it('hides photos the host register already shows itself', async () => {
    vi.mocked(api.fetchByTarget).mockResolvedValue([
      photo('own', { source_module: 'punchlist' }),
      photo('linked'),
    ]);
    wrap(<PhotoStrip projectId="proj" kind="punch_item" targetId="i" hideSource="punchlist" canUpload={false} />);
    expect(await screen.findByRole('button', { name: 'Caption linked' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Caption own' })).toBeNull();
  });

  it('renders nothing until the record exists', () => {
    const { container } = wrap(<PhotoStrip projectId="proj" kind="diary" targetId={null} />);
    expect(container.querySelector('[data-testid="photo-strip"]')).toBeNull();
    expect(api.fetchByTarget).not.toHaveBeenCalled();
  });
});

describe('BeforeAfterSlider', () => {
  it('moves the split with the keyboard and clips the before photo to it', () => {
    wrap(<BeforeAfterSlider before={photo('b')} after={photo('a')} />);
    const handle = screen.getByRole('slider');
    expect(handle.getAttribute('aria-valuenow')).toBe('50');
    fireEvent.keyDown(handle, { key: 'ArrowRight' });
    fireEvent.keyDown(handle, { key: 'PageUp' });
    expect(handle.getAttribute('aria-valuenow')).toBe('62');
    expect(screen.getByTestId('before-layer').style.clipPath).toBe('inset(0 38% 0 0)');
    fireEvent.keyDown(handle, { key: 'Home' });
    expect(handle.getAttribute('aria-valuenow')).toBe('0');
  });
});

describe('AISuggestionList', () => {
  const pending = (kind: Suggestion['kind'], payload: Record<string, unknown>, id: string): Suggestion => ({
    id,
    photo_id: 'p',
    kind,
    payload,
    confidence: 0.8,
    provider: 'x',
    model: 'y',
    status: 'pending',
    reviewed_by: null,
    reviewed_at: null,
    created_at: null,
  });

  it('accepts unchanged, accepts an edit, and rejects', async () => {
    vi.mocked(api.fetchSuggestions).mockResolvedValue([
      pending('caption', { text: 'Rebar in bay 3' }, 's1'),
      pending('tags', { tags: ['rebar'] }, 's2'),
    ]);
    vi.mocked(api.acceptSuggestion).mockResolvedValue({} as Suggestion);
    vi.mocked(api.rejectSuggestion).mockResolvedValue({} as Suggestion);
    wrap(<AISuggestionList photoId="p" canRun={false} />);

    const caption = await screen.findByTestId('suggestion-caption');
    fireEvent.click(caption.querySelector('button')!);
    await waitFor(() => expect(api.acceptSuggestion).toHaveBeenCalledWith('s1', undefined));

    const tags = screen.getByTestId('suggestion-tags');
    fireEvent.change(tags.querySelector('input')!, { target: { value: 'rebar, Slab' } });
    fireEvent.click(tags.querySelector('button')!);
    await waitFor(() => expect(api.acceptSuggestion).toHaveBeenCalledWith('s2', { tags: ['rebar', 'slab'] }));

    fireEvent.click(caption.querySelectorAll('button')[1]!);
    await waitFor(() => expect(api.rejectSuggestion).toHaveBeenCalledWith('s1'));
  });

  it('blocks accepting an edit the API would refuse', async () => {
    vi.mocked(api.fetchSuggestions).mockResolvedValue([
      pending('progress', { target_kind: 'boq_position', target_id: 'x', percent_observed: 40 }, 's3'),
    ]);
    wrap(<AISuggestionList photoId="p" canRun={false} />);
    const row = await screen.findByTestId('suggestion-progress');
    fireEvent.change(row.querySelector('input')!, { target: { value: '250' } });
    expect((row.querySelector('button') as HTMLButtonElement).disabled).toBe(true);
  });
});
