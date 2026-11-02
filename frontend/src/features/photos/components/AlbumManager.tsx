// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Named sets of photos: handover packs, claim evidence, monthly progress.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, FolderPlus, Images, Trash2 } from 'lucide-react';
import { ConfirmDialog, EmptyState, ErrorState } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { createAlbum, deleteAlbum, fetchAlbums, photosKeys, type Album } from '../api';

interface AlbumManagerProps {
  projectId: string;
  onOpen: (album: Album) => void;
  onExport: (album: Album) => void;
}

export function AlbumManager({ projectId, onOpen, onExport }: AlbumManagerProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [name, setName] = useState('');
  const [toDelete, setToDelete] = useState<Album | null>(null);
  const albums = useQuery({ queryKey: photosKeys.albums(projectId), queryFn: () => fetchAlbums(projectId) });

  const create = useMutation({
    mutationFn: () => createAlbum(projectId, name.trim()),
    onSuccess: () => {
      setName('');
      qc.invalidateQueries({ queryKey: photosKeys.albums(projectId) });
    },
    onError: (err) => addToast({ type: 'error', title: t('photoArchive.albums.create_failed'), message: getErrorMessage(err) }),
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteAlbum(id),
    onSuccess: () => {
      setToDelete(null);
      qc.invalidateQueries({ queryKey: photosKeys.albums(projectId) });
    },
  });

  return (
    <div className="space-y-4">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) create.mutate();
        }}
      >
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('photoArchive.albums.name_placeholder')}
          aria-label={t('photoArchive.albums.name')}
          maxLength={200}
          className="min-w-0 flex-1 rounded-md border border-border-light bg-surface-primary px-3 py-1.5 text-sm"
        />
        <button
          type="submit"
          disabled={!name.trim() || create.isPending}
          className="inline-flex items-center gap-1 rounded-md bg-oe-blue px-3 py-1.5 text-sm text-white disabled:opacity-50"
        >
          <FolderPlus className="h-4 w-4" aria-hidden />
          {t('photoArchive.albums.create')}
        </button>
      </form>

      {albums.isError ? (
        <ErrorState title={t('photoArchive.albums.load_failed')} onRetry={() => albums.refetch()} />
      ) : (albums.data ?? []).length === 0 && !albums.isLoading ? (
        <EmptyState
          icon={<Images className="h-8 w-8" />}
          title={t('photoArchive.albums.empty_title')}
          description={t('photoArchive.albums.empty_body')}
        />
      ) : (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {(albums.data ?? []).map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-2 rounded-lg border border-border-light p-3">
              <button type="button" onClick={() => onOpen(a)} className="min-w-0 text-left">
                <div className="truncate text-sm font-medium">{a.name}</div>
                <div className="text-xs text-content-tertiary">
                  {t('photoArchive.albums.count', { count: a.photo_count })}
                </div>
              </button>
              <div className="flex shrink-0 gap-1">
                <button
                  type="button"
                  onClick={() => onExport(a)}
                  disabled={a.photo_count === 0}
                  className="rounded p-1.5 hover:bg-surface-secondary disabled:opacity-40"
                  aria-label={t('photoArchive.export.album')}
                >
                  <Download className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  onClick={() => setToDelete(a)}
                  className="rounded p-1.5 text-semantic-error hover:bg-surface-secondary"
                  aria-label={t('photoArchive.albums.delete')}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={toDelete !== null}
        onCancel={() => setToDelete(null)}
        onConfirm={() => toDelete && remove.mutate(toDelete.id)}
        loading={remove.isPending}
        variant="danger"
        title={t('photoArchive.albums.delete_title')}
        message={t('photoArchive.albums.delete_message', { name: toDelete?.name ?? '' })}
        confirmLabel={t('photoArchive.albums.delete')}
      />
    </div>
  );
}
