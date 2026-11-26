import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';

vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  deletePhoto: vi.fn(),
  patchPhoto: vi.fn(),
  setPhotoAlbums: vi.fn(),
  fetchAlbums: vi.fn(),
}));

import * as api from '../api';
import { useAuthStore } from '@/stores/useAuthStore';
import type { ArchivePhoto } from '../api';
import { BulkBar } from '../components/BulkBar';
import { PhotoMetaEditor, dayDiaryRoute, raiseRoute } from '../components/PhotoMetaEditor';
import { bulkPatch, categorySuggestion } from '../model';

function photo(id: string, extra: Partial<ArchivePhoto> = {}): ArchivePhoto {
  return {
    id,
    project_id: 'proj',
    filename: `${id}.jpg`,
    caption: null,
    category: 'site',
    tags: [],
    taken_at: '2026-10-05T09:00:00Z',
    created_at: null,
    created_by: '',
    gps_lat: null,
    gps_lon: null,
    gps_accuracy_m: null,
    width: null,
    height: null,
    sha256: null,
    source_module: 'documents',
    source_id: null,
    thumb_status: 'ready',
    location_id: null,
    zone: null,
    is_archived: false,
    evidence_grade: 'none',
    taken_at_source: null,
    file_url: '',
    thumb_url: '',
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

const updatePhoto = vi.mocked(api.patchPhoto);

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ userRole: 'editor' });
  updatePhoto.mockResolvedValue({} as never);
  vi.mocked(api.fetchAlbums).mockResolvedValue([]);
});

const photos = [photo('a', { tags: ['Rebar'] }), photo('b', { category: 'defect', tags: ['field'] }), photo('c')];

describe('bulk category', () => {
  it('patches only the selected photos that differ, on the gallery endpoint', async () => {
    const onSelect = vi.fn();
    wrap(<BulkBar photos={photos} selected={['a', 'b']} allIds={['a', 'b', 'c']} onSelect={onSelect} />);
    fireEvent.change(screen.getByRole('combobox', { name: /category/i }), { target: { value: 'defect' } });
    await waitFor(() => expect(updatePhoto).toHaveBeenCalledTimes(1));
    expect(updatePhoto).toHaveBeenCalledWith('a', { category: 'defect' });
  });

  it('keeps the failed photos selected', async () => {
    updatePhoto.mockRejectedValueOnce(new Error('no'));
    const onSelect = vi.fn();
    wrap(<BulkBar photos={photos} selected={['a', 'c']} allIds={['a', 'b', 'c']} onSelect={onSelect} />);
    fireEvent.change(screen.getByRole('combobox', { name: /category/i }), { target: { value: 'safety' } });
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(['a']));
  });

  it('selects all and clears', () => {
    const onSelect = vi.fn();
    wrap(<BulkBar photos={photos} selected={['a']} allIds={['a', 'b', 'c']} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole('button', { name: /bulk.select_all/ }));
    expect(onSelect).toHaveBeenCalledWith(['a', 'b', 'c']);
  });
});

describe('bulk tags', () => {
  it('adds typed tags without duplicating ones a photo already has', async () => {
    wrap(<BulkBar photos={photos} selected={['a', 'c']} allIds={['a', 'b', 'c']} onSelect={vi.fn()} />);
    fireEvent.change(screen.getByRole('textbox', { name: /bulk.add_tags/ }), { target: { value: 'rebar, slab, slab' } });
    fireEvent.submit(screen.getByRole('textbox', { name: /bulk.add_tags/ }).closest('form')!);
    await waitFor(() => expect(updatePhoto).toHaveBeenCalledTimes(2));
    expect(updatePhoto).toHaveBeenCalledWith('a', { tags: ['Rebar', 'slab'] });
    expect(updatePhoto).toHaveBeenCalledWith('c', { tags: ['rebar', 'slab'] });
  });

  it('removes the selected photos through the archive endpoint after confirming', async () => {
    vi.mocked(api.deletePhoto).mockResolvedValue({ result: 'deleted' });
    const onSelect = vi.fn();
    wrap(<BulkBar photos={photos} selected={['a', 'b']} allIds={['a', 'b', 'c']} onSelect={onSelect} />);
    fireEvent.click(screen.getAllByRole('button', { name: /bulk.remove/ })[0]!);
    const dialogButtons = await screen.findAllByRole('button', { name: /bulk.remove/ });
    fireEvent.click(dialogButtons[dialogButtons.length - 1]!);
    await waitFor(() => expect(api.deletePhoto).toHaveBeenCalledTimes(2));
    expect(onSelect).toHaveBeenLastCalledWith([]);
  });
});

describe('field photo toggle', () => {
  it('bulk marks and unmarks only where needed', async () => {
    wrap(<BulkBar photos={photos} selected={['a', 'b']} allIds={['a', 'b']} onSelect={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /bulk.mark_field/ }));
    await waitFor(() => expect(updatePhoto).toHaveBeenCalledTimes(1));
    expect(updatePhoto).toHaveBeenCalledWith('a', { tags: ['Rebar', 'field'] });
    fireEvent.click(screen.getByRole('button', { name: /bulk.unmark_field/ }));
    await waitFor(() => expect(updatePhoto).toHaveBeenCalledWith('b', { tags: [] }));
  });

  it('flips the flag on one photo from the lightbox editor', async () => {
    wrap(<PhotoMetaEditor photo={photo('x', { tags: ['slab'] })} />);
    const toggle = screen.getByRole('button', { pressed: false });
    fireEvent.click(toggle);
    await waitFor(() => expect(updatePhoto).toHaveBeenCalledWith('x', { tags: ['slab', 'field'] }));
  });

  it('pure rule: no request when nothing changes', () => {
    expect(bulkPatch({ category: 'site', tags: ['FIELD'] }, { kind: 'field', on: true })).toBeNull();
    expect(bulkPatch({ category: 'site', tags: [] }, { kind: 'category', category: 'site' })).toBeNull();
  });
});

describe('kept gallery behaviour', () => {
  it('reads a category suggestion only when it differs and is valid', () => {
    expect(categorySuggestion(photo('s', { category_suggestion: { suggested_category: 'defect', confidence: 0.7 } }))).toEqual({
      category: 'defect',
      confidence: 0.7,
      tags: [],
    });
    expect(categorySuggestion(photo('s', { category_suggestion: { suggested_category: 'site' } }))).toBeNull();
    expect(categorySuggestion(photo('s', { category_suggestion: { suggested_category: 'spaceship' } }))).toBeNull();
  });

  it('raises records and opens the day diary with the same links as before', () => {
    const p = photo('r', { caption: 'Crack' });
    expect(raiseRoute(p, 'punch')).toBe('/punchlist?create=true&photo_id=r&title=Crack');
    expect(raiseRoute(p, 'ncr').startsWith('/ncr?')).toBe(true);
    expect(dayDiaryRoute(p)).toBe('/daily-diary?date=2026-10-05');
  });
});

describe('photo detail drawer: category and album', () => {
  const albums = [
    { id: 'al-1', project_id: 'proj', name: 'Punch walk L2', description: null, cover_photo_id: null, sort_order: 0, photo_count: 3, created_at: null },
    { id: 'al-2', project_id: 'proj', name: 'Handover', description: null, cover_photo_id: null, sort_order: 1, photo_count: 0, created_at: null },
  ];

  it('keeps the chosen category after the save and reads it back from the server', async () => {
    updatePhoto.mockResolvedValue(photo('x', { category: 'defect' }));
    const onChange = vi.fn();
    wrap(<PhotoMetaEditor photo={photo('x')} onChange={onChange} />);
    const select = screen.getByTestId('photo-category-select') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'defect' } });
    await waitFor(() => expect(updatePhoto).toHaveBeenCalledWith('x', { category: 'defect' }));
    await screen.findByTestId('photo-saved-category');
    expect(select.value).toBe('defect');
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: 'x', category: 'defect' }));
  });

  it('goes back to the stored category when the save fails', async () => {
    updatePhoto.mockRejectedValueOnce(new Error('no'));
    wrap(<PhotoMetaEditor photo={photo('x', { category: 'progress' })} />);
    const select = screen.getByTestId('photo-category-select') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'safety' } });
    await waitFor(() => expect(select.value).toBe('progress'));
  });

  it('puts the photo in an album and takes it out again', async () => {
    vi.mocked(api.fetchAlbums).mockResolvedValue(albums);
    vi.mocked(api.setPhotoAlbums).mockResolvedValueOnce(photo('x', { album_ids: ['al-2'] }));
    wrap(<PhotoMetaEditor photo={photo('x', { album_ids: ['al-1'] })} />);
    const select = (await screen.findByTestId('photo-album-select')) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe('al-1'));
    fireEvent.change(select, { target: { value: 'al-2' } });
    await waitFor(() => expect(api.setPhotoAlbums).toHaveBeenCalledWith('x', ['al-2']));
    await screen.findByTestId('photo-saved-album');
    expect(select.value).toBe('al-2');

    vi.mocked(api.setPhotoAlbums).mockResolvedValueOnce(photo('x', { album_ids: [] }));
    fireEvent.change(select, { target: { value: '' } });
    await waitFor(() => expect(api.setPhotoAlbums).toHaveBeenLastCalledWith('x', []));
    await waitFor(() => expect(select.value).toBe(''));
  });

  it('says when the project has no albums yet', async () => {
    wrap(<PhotoMetaEditor photo={photo('x')} />);
    expect(await screen.findByText('photoArchive.meta.no_albums_hint')).toBeInTheDocument();
  });

  it('shows a viewer the values but not the controls to change them', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    vi.mocked(api.fetchAlbums).mockResolvedValue(albums);
    wrap(<PhotoMetaEditor photo={photo('x', { category: 'defect' })} />);
    const category = screen.getByTestId('photo-category-select') as HTMLSelectElement;
    expect(category).toBeDisabled();
    expect(category.value).toBe('defect');
    expect(category.closest('label')).toHaveAttribute('title', 'photoArchive.meta.edit_needs_editor');
    expect(await screen.findByTestId('photo-album-select')).toBeDisabled();
  });
});
