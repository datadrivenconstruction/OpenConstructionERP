/**
 * Files attached to one submittal: list, upload, download, delete.
 *
 * Rendered inside the expanded row, so the list is fetched when the row is
 * opened rather than once per row of the register. Linked documents (attached
 * by id from the documents module) are listed, but only uploaded files carry a
 * download here.
 */
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, Loader2, Paperclip, Trash2, Upload } from 'lucide-react';

import { ConfirmDialog, DateDisplay } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  deleteSubmittalAttachment,
  downloadSubmittalAttachment,
  fetchSubmittalAttachments,
  uploadSubmittalAttachment,
  type SubmittalAttachment,
} from './api';

function formatSize(bytes: number | null): string {
  if (bytes == null) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function SubmittalAttachments({
  submittalId,
  readOnly = false,
}: {
  submittalId: string;
  readOnly?: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const fileRef = useRef<HTMLInputElement>(null);
  const [pendingDelete, setPendingDelete] = useState<SubmittalAttachment | null>(null);
  const queryKey = ['submittals', submittalId, 'attachments'];

  const listQ = useQuery({ queryKey, queryFn: () => fetchSubmittalAttachments(submittalId) });
  const refresh = () => qc.invalidateQueries({ queryKey });
  const fail = (err: unknown) =>
    addToast({ type: 'error', title: err instanceof Error ? err.message : String(err) });

  const uploadMut = useMutation({
    mutationFn: (file: File) => uploadSubmittalAttachment(submittalId, file),
    onSuccess: () => {
      refresh();
      addToast({
        type: 'success',
        title: t('submittals.attachment_uploaded', { defaultValue: 'File attached' }),
      });
    },
    onError: fail,
  });
  const deleteMut = useMutation({
    mutationFn: (att: SubmittalAttachment) =>
      deleteSubmittalAttachment(submittalId, att.document_id),
    onSuccess: () => {
      refresh();
      setPendingDelete(null);
    },
    onError: fail,
  });

  const items = listQ.data ?? [];

  return (
    <div data-testid={`submittal-attachments-${submittalId}`}>
      <div className="mb-1 flex items-center gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-content-tertiary">
          <Paperclip size={11} className="me-1 inline" />
          {t('submittals.attachments', { defaultValue: 'Attachments' })}
        </span>
        <span className="text-xs tabular-nums text-content-tertiary">{items.length}</span>
        {!readOnly && (
          <>
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              data-testid="submittal-attachment-input"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = '';
                if (file) uploadMut.mutate(file);
              }}
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={uploadMut.isPending}
              className="ms-auto inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-oe-blue hover:bg-oe-blue-subtle disabled:opacity-50"
              data-testid="submittal-attachment-upload"
            >
              {uploadMut.isPending ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Upload size={12} />
              )}
              {t('submittals.attachment_upload', { defaultValue: 'Upload file' })}
            </button>
          </>
        )}
      </div>

      {listQ.isLoading ? (
        <p className="text-xs text-content-tertiary">
          {t('common.loading', { defaultValue: 'Loading...' })}
        </p>
      ) : items.length === 0 ? (
        <p className="text-xs text-content-tertiary">
          {t('submittals.attachments_empty', { defaultValue: 'No files attached yet.' })}
        </p>
      ) : (
        <ul className="divide-y divide-border-light rounded-lg border border-border-light">
          {items.map((att) => (
            <li
              key={att.document_id}
              className="flex items-center gap-2 px-3 py-1.5 text-xs"
              data-testid={`submittal-attachment-${att.document_id}`}
            >
              <span className="min-w-0 flex-1 truncate text-content-primary" title={att.label}>
                {att.label || att.document_id}
              </span>
              <span className="tabular-nums text-content-tertiary">
                {formatSize(att.size_bytes)}
              </span>
              {att.added_at && (
                <DateDisplay value={att.added_at} className="text-xs text-content-tertiary" />
              )}
              {att.downloadable && (
                <button
                  type="button"
                  onClick={() => downloadSubmittalAttachment(submittalId, att).catch(fail)}
                  className="rounded p-1 text-content-secondary hover:bg-oe-blue-subtle hover:text-oe-blue-text"
                  aria-label={t('submittals.attachment_download', { defaultValue: 'Download' })}
                  title={t('submittals.attachment_download', { defaultValue: 'Download' })}
                  data-testid={`submittal-attachment-download-${att.document_id}`}
                >
                  <Download size={13} />
                </button>
              )}
              {!readOnly && (
                <button
                  type="button"
                  onClick={() => setPendingDelete(att)}
                  className="rounded p-1 text-content-secondary hover:bg-semantic-error-bg hover:text-semantic-error"
                  aria-label={t('common.delete', { defaultValue: 'Delete' })}
                  title={t('common.delete', { defaultValue: 'Delete' })}
                  data-testid={`submittal-attachment-delete-${att.document_id}`}
                >
                  <Trash2 size={13} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title={t('submittals.attachment_delete_title', { defaultValue: 'Remove attachment' })}
        message={t('submittals.attachment_delete_message', {
          defaultValue: 'Remove "{{name}}" from this submittal?',
          name: pendingDelete?.label ?? '',
        })}
        loading={deleteMut.isPending}
        onConfirm={() => pendingDelete && deleteMut.mutate(pendingDelete)}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}
