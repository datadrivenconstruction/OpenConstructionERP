// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The step that puts a file behind a frame document, opened in place under
// the document. Two ways in: upload a file, which is what most people have,
// or point at a container the project already keeps in the CDE. A document
// that already has a container only takes a new file, which becomes its
// newest revision.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { FolderOpen, Upload } from 'lucide-react';

import { fetchCDEContainers } from '@/features/cde/api';
import { Button } from '@/shared/ui/Button';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

import { attachDocument, governanceKeys, type FrameDocument } from './api';
import { attachFileToDocument } from './documentFiles';
import { refusalText } from './labels';

type Mode = 'upload' | 'container';

export interface DocumentAttachProps {
  projectId: string;
  doc: FrameDocument;
  areaCode: string;
  /** The document's name as the reader sees it. */
  title: string;
  onDone: () => void;
  onCancel: () => void;
}

export function DocumentAttach({ projectId, doc, areaCode, title, onDone, onCancel }: DocumentAttachProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const hasContainer = !!doc.container_id;
  const [mode, setMode] = useState<Mode>('upload');
  const [file, setFile] = useState<File | null>(null);
  const [containerId, setContainerId] = useState('');

  const containers = useQuery({
    queryKey: governanceKeys.containers(projectId),
    queryFn: () => fetchCDEContainers({ project_id: projectId }),
    enabled: !hasContainer,
  });

  const onError = (err: unknown) => addToast({ type: 'error', title: refusalText(t, err) });
  const upload = useMutation({
    mutationFn: (chosen: File) =>
      attachFileToDocument({ projectId, doc, areaCode, title, file: chosen, containers: containers.data ?? [] }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('governance.project.attach.file_added', { defaultValue: 'File added as the newest revision' }),
      });
      onDone();
    },
    onError,
  });
  const link = useMutation({
    mutationFn: (id: string) => attachDocument(projectId, doc.id, id),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('governance.project.attach.container_attached', { defaultValue: 'Container attached' }),
      });
      onDone();
    },
    onError,
  });
  const busy = upload.isPending || link.isPending;
  const list = containers.data ?? [];

  return (
    <div className="mt-2 space-y-3 rounded-md bg-surface-secondary p-3" data-testid="document-attach">
      <p className="text-xs text-content-secondary">
        {hasContainer
          ? t('governance.project.attach.revision_intro', {
              defaultValue: 'The file becomes the newest revision of this document. The gate reviews the newest revision.',
            })
          : t('governance.project.attach.intro', {
              defaultValue:
                'A frame document needs a file before it can go to gate review. Upload it here, or use a container the project already keeps in the CDE.',
            })}
      </p>

      {!hasContainer && (
        <div className="flex flex-wrap gap-4 text-sm" role="radiogroup" aria-label={t('governance.project.attach.mode', { defaultValue: 'Where the file comes from' })}>
          <label className="inline-flex items-center gap-1.5">
            <input type="radio" name={`attach-${doc.id}`} checked={mode === 'upload'} onChange={() => setMode('upload')} />
            <Upload size={13} aria-hidden />
            {t('governance.project.attach.mode_upload', { defaultValue: 'Upload a file' })}
          </label>
          <label className="inline-flex items-center gap-1.5">
            <input type="radio" name={`attach-${doc.id}`} checked={mode === 'container'} onChange={() => setMode('container')} />
            <FolderOpen size={13} aria-hidden />
            {t('governance.project.attach.mode_container', { defaultValue: 'Use a CDE container' })}
          </label>
        </div>
      )}

      {(hasContainer || mode === 'upload') && (
        <input
          type="file"
          data-testid="attach-file-input"
          aria-label={t('governance.project.attach.file', { defaultValue: 'File' })}
          className="block w-full text-sm text-content-primary file:mr-3 file:rounded-md file:border file:border-border-light file:bg-surface-primary file:px-3 file:py-1 file:text-sm"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      )}

      {!hasContainer && mode === 'container' && (
        <div data-testid="attach-containers">
          {containers.isLoading && (
            <p className="text-xs text-content-tertiary">{t('governance.project.loading', { defaultValue: 'Loading...' })}</p>
          )}
          {containers.isError && (
            <p className="flex flex-wrap items-center gap-2 text-xs text-semantic-error" role="alert">
              {t('governance.project.attach.containers_failed', { defaultValue: 'The CDE containers could not be loaded.' })}{' '}
              {getErrorMessage(containers.error)}
              <Button size="sm" variant="ghost" onClick={() => containers.refetch()}>
                {t('governance.project.retry', { defaultValue: 'Try again' })}
              </Button>
            </p>
          )}
          {containers.isSuccess && list.length === 0 && (
            <p className="text-xs text-content-tertiary">
              {t('governance.project.attach.no_containers', {
                defaultValue: 'This project has no CDE container yet. Upload a file instead and a container is created for it.',
              })}
            </p>
          )}
          {list.length > 0 && (
            <select
              aria-label={t('governance.project.attach.container', { defaultValue: 'CDE container' })}
              className="w-full rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary"
              value={containerId}
              onChange={(e) => setContainerId(e.target.value)}
            >
              <option value="">{t('governance.project.attach.choose_container', { defaultValue: 'Choose a container' })}</option>
              {list.map((c) => (
                <option key={c.id} value={c.id}>
                  {t('governance.project.attach.container_option', {
                    defaultValue: '{{code}}: {{title}}',
                    code: c.container_code,
                    title: c.title,
                  })}
                </option>
              ))}
            </select>
          )}
        </div>
      )}

      <div className="flex gap-2">
        {hasContainer || mode === 'upload' ? (
          <Button size="sm" disabled={!file} loading={busy} onClick={() => file && upload.mutate(file)} data-testid="attach-send">
            {hasContainer
              ? t('governance.project.attach.add_revision', { defaultValue: 'Add as new revision' })
              : t('governance.project.attach.upload_send', { defaultValue: 'Upload and attach' })}
          </Button>
        ) : (
          <Button size="sm" disabled={!containerId} loading={busy} onClick={() => link.mutate(containerId)} data-testid="attach-send">
            {t('governance.project.attach.container_send', { defaultValue: 'Attach container' })}
          </Button>
        )}
        <Button size="sm" variant="ghost" disabled={busy} onClick={onCancel}>
          {t('governance.project.cancel', { defaultValue: 'Cancel' })}
        </Button>
      </div>
    </div>
  );
}
