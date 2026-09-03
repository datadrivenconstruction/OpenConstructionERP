// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ProjectProposalChip — the original proposal, attached to the project header.
 *
 * Nothing attached: a quiet "＋ Attach the original proposal" action.
 * Attached: a chip with the file name (size + date in its tooltip) that opens
 * a viewer popup on click, and a right-click menu offering Open, Download,
 * Replace… and Remove.
 *
 * Storage — no new upload path was invented:
 *   1. the file goes to the existing Documents endpoint,
 *      ``POST /api/v1/documents/upload/?project_id=…&category=contract``
 *      (multipart, field name ``file``) — the same one the Documents page and
 *      the file-manager upload dialog use;
 *   2. a pointer is written onto the project with
 *      ``PATCH /api/v1/projects/{id}`` as ``metadata.proposal``.
 *
 * That PATCH shallow-merges ``metadata`` server-side
 * (``app/core/json_merge.py::merge_metadata``), so writing the single
 * ``proposal`` key leaves every other metadata key intact. It is called
 * directly rather than through ``projectsApi.update`` because
 * ``UpdateProjectData`` does not model ``metadata``.
 *
 * The viewer reuses ``InlinePdfPreviewModal`` for PDFs (bearer-protected
 * bytes → blob URL → iframe, with download and open-in-new-tab already built
 * in) rather than growing a second PDF viewer. Images and everything else are
 * handled by the small modal below, using the same authenticated-blob helpers.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  FileText,
  Paperclip,
  X,
  Download,
  ExternalLink,
  Loader2,
} from 'lucide-react';
import { apiPatch } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  fetchProtectedObjectUrl,
  downloadProtectedFile,
} from '@/features/file-manager/api';
import { InlinePdfPreviewModal } from '@/features/file-references/InlinePdfPreviewModal';
import { useModalDismiss } from './useModalDismiss';
import { fmtFixed } from '@/shared/lib/formatters';

/** What we persist on ``project.metadata.proposal``. */
export interface ProposalPointer {
  file_id: string;
  filename: string;
  content_type: string;
  size: number;
  uploaded_at: string;
  uploaded_by: string;
}

/**
 * Client-side cap. The backend accepts far more (500 MB), but a proposal that
 * large is a mis-drop, and the honest message points at the Documents page
 * rather than silently failing.
 */
export const MAX_PROPOSAL_BYTES = 40 * 1024 * 1024;

const ACCEPTED =
  '.pdf,.doc,.docx,.png,.jpg,.jpeg,.webp,.gif,application/pdf,image/*';

const ACCEPTED_EXTENSIONS = ['pdf', 'doc', 'docx', 'png', 'jpg', 'jpeg', 'webp', 'gif'];

export function formatBytes(bytes: number): string {
  if (!bytes || bytes < 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${fmtFixed(kb, 0)} KB`;
  return `${fmtFixed(kb / 1024, 1)} MB`;
}

function isImage(contentType: string, filename: string): boolean {
  if (contentType.startsWith('image/')) return true;
  return /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(filename);
}

function isPdf(contentType: string, filename: string): boolean {
  return contentType === 'application/pdf' || /\.pdf$/i.test(filename);
}

/** Read the pointer off a project's metadata, tolerating junk. */
export function readProposal(
  metadata: Record<string, unknown> | undefined | null,
): ProposalPointer | null {
  const raw = metadata?.proposal;
  if (!raw || typeof raw !== 'object') return null;
  const p = raw as Partial<ProposalPointer>;
  if (!p.file_id || !p.filename) return null;
  return {
    file_id: String(p.file_id),
    filename: String(p.filename),
    content_type: String(p.content_type ?? ''),
    size: Number(p.size ?? 0),
    uploaded_at: String(p.uploaded_at ?? ''),
    uploaded_by: String(p.uploaded_by ?? ''),
  };
}

/* ── Non-PDF viewer ───────────────────────────────────────────────────── */

function ProposalViewerModal({
  proposal,
  downloadUrl,
  onClose,
}: {
  proposal: ProposalPointer;
  downloadUrl: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const image = isImage(proposal.content_type, proposal.filename);
  useModalDismiss(true, onClose);

  // Only images need the bytes inline; for anything else we just offer the
  // download rather than pulling a 30 MB Word file into memory to show a box.
  useEffect(() => {
    if (!image) return undefined;
    let cancelled = false;
    let created: string | null = null;
    void fetchProtectedObjectUrl(downloadUrl).then((url) => {
      if (cancelled) {
        if (url) URL.revokeObjectURL(url);
        return;
      }
      if (!url) {
        setFailed(true);
        return;
      }
      created = url;
      setObjectUrl(url);
    });
    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [image, downloadUrl]);

  const handleDownload = useCallback(async () => {
    setDownloading(true);
    try {
      await downloadProtectedFile(downloadUrl, proposal.filename);
    } catch {
      setFailed(true);
    } finally {
      setDownloading(false);
    }
  }, [downloadUrl, proposal.filename]);

  // Portalled: the header Card is inside an animated container, and a
  // transformed ancestor becomes the containing block for `position: fixed`.
  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={proposal.filename}
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      data-testid="proposal-viewer"
    >
      <div
        className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-lg bg-surface-elevated shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between gap-2 border-b border-border-light px-4 py-2.5">
          <span
            className="truncate text-sm font-semibold text-content-primary"
            title={proposal.filename}
          >
            {proposal.filename}
          </span>
          <div className="flex shrink-0 items-center gap-1">
            {objectUrl && (
              <a
                href={objectUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex h-7 items-center gap-1 rounded-md border border-border-light px-2 text-[11px] font-medium text-content-secondary hover:bg-surface-secondary"
              >
                <ExternalLink size={12} />
                {t('files.preview.open_new_tab_short', { defaultValue: 'New tab' })}
              </a>
            )}
            <button
              type="button"
              onClick={handleDownload}
              disabled={downloading}
              data-testid="proposal-viewer-download"
              className="inline-flex h-7 items-center gap-1 rounded-md border border-border-light px-2 text-[11px] font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-50"
            >
              {downloading ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Download size={12} />
              )}
              {t('files.actions.download', { defaultValue: 'Download' })}
            </button>
            <button
              type="button"
              onClick={onClose}
              aria-label={t('common.close', { defaultValue: 'Close' })}
              data-testid="proposal-viewer-close"
              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
            >
              <X size={15} />
            </button>
          </div>
        </header>
        <div className="flex min-h-[16rem] flex-1 items-center justify-center overflow-auto bg-surface-secondary/40 p-4">
          {image && objectUrl ? (
            <img
              src={objectUrl}
              alt={proposal.filename}
              className="max-h-full max-w-full object-contain"
              data-testid="proposal-viewer-image"
            />
          ) : image && !failed ? (
            <Loader2 size={26} className="animate-spin text-content-tertiary" />
          ) : (
            <div className="max-w-sm text-center">
              <p className="text-sm text-content-secondary" data-testid="proposal-viewer-note">
                {failed
                  ? t('projects.proposal.preview_failed', {
                      defaultValue: 'This file could not be previewed.',
                    })
                  : t('projects.proposal.no_inline_preview', {
                      type: proposal.content_type || t('common.unknown', { defaultValue: 'unknown' }),
                      defaultValue:
                        'This is a {{type}} file, which cannot be shown inline. Download it to open it.',
                    })}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

/* ── The chip ─────────────────────────────────────────────────────────── */

export interface ProjectProposalChipProps {
  projectId: string;
  metadata: Record<string, unknown> | undefined | null;
  /** Owner / admin: hides attach, replace and remove for everybody else. */
  canManage?: boolean;
}

export function ProjectProposalChip({
  projectId,
  metadata,
  canManage = true,
}: ProjectProposalChipProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const proposal = useMemo(() => readProposal(metadata), [metadata]);
  const downloadUrl = proposal
    ? `/api/v1/documents/${proposal.file_id}/download`
    : '';

  const savePointer = useMutation({
    mutationFn: (pointer: ProposalPointer | null) =>
      // metadata is shallow-merged server-side, so this touches only
      // `proposal` and leaves the project's other metadata keys alone.
      apiPatch<unknown>(`/v1/projects/${projectId}`, {
        metadata: { proposal: pointer },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
    },
  });

  const upload = useCallback(
    async (file: File) => {
      setError(null);

      const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
      if (!ACCEPTED_EXTENSIONS.includes(ext)) {
        setError(
          t('projects.proposal.bad_type', {
            defaultValue:
              'Attach a PDF, Word document or image — that file type is not accepted here.',
          }),
        );
        return;
      }
      if (file.size > MAX_PROPOSAL_BYTES) {
        setError(
          t('projects.proposal.too_big', {
            size: formatBytes(file.size),
            max: formatBytes(MAX_PROPOSAL_BYTES),
            defaultValue:
              'That file is {{size}} — the proposal slot is capped at {{max}}. Upload it on the Files tab and link it from there.',
          }),
        );
        return;
      }

      setPending(true);
      try {
        // Multipart cannot go through apiPost: `request()` forces a JSON
        // Content-Type when a body is present, which breaks the boundary.
        // Same raw-fetch shape as features/documents/api.ts::uploadDocument.
        const form = new FormData();
        form.append('file', file);
        const token = useAuthStore.getState().accessToken;
        const res = await fetch(
          `/api/v1/documents/upload/?project_id=${encodeURIComponent(projectId)}&category=contract`,
          {
            method: 'POST',
            headers: {
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
              'X-DDC-Client': 'OE/1.0',
            },
            body: form,
          },
        );
        if (!res.ok) {
          let detail = '';
          try {
            detail = ((await res.json()) as { detail?: string }).detail ?? '';
          } catch {
            detail = '';
          }
          throw new Error(
            detail ||
              t('projects.proposal.upload_failed', {
                defaultValue: 'The upload was refused.',
              }),
          );
        }
        const doc = (await res.json()) as {
          id: string;
          name: string;
          mime_type?: string;
          file_size?: number;
          created_at?: string;
          uploaded_by?: string;
        };
        await savePointer.mutateAsync({
          file_id: doc.id,
          filename: doc.name || file.name,
          content_type: doc.mime_type || file.type || '',
          size: doc.file_size ?? file.size,
          uploaded_at: doc.created_at ?? new Date().toISOString(),
          uploaded_by: doc.uploaded_by ?? '',
        });
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : t('projects.proposal.upload_failed', {
                defaultValue: 'The upload was refused.',
              }),
        );
      } finally {
        setPending(false);
      }
    },
    [projectId, savePointer, t],
  );

  // Close the context menu on an outside click or Escape.
  useEffect(() => {
    if (!menu) return undefined;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenu(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenu(null);
    };
    window.addEventListener('mousedown', onDown);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('mousedown', onDown);
      window.removeEventListener('keydown', onKey);
    };
  }, [menu]);

  const pickFile = useCallback(() => fileInputRef.current?.click(), []);

  const openInNewTab = useCallback(async () => {
    const url = await fetchProtectedObjectUrl(downloadUrl);
    if (url) window.open(url, '_blank', 'noopener,noreferrer');
  }, [downloadUrl]);

  const tooltip = proposal
    ? [
        proposal.filename,
        formatBytes(proposal.size),
        proposal.uploaded_at ? proposal.uploaded_at.slice(0, 10) : '',
      ]
        .filter(Boolean)
        .join(' · ')
    : '';

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept={ACCEPTED}
        className="hidden"
        data-testid="proposal-file-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          // Reset first so re-picking the same file fires change again.
          e.target.value = '';
          if (file) void upload(file);
        }}
      />

      {proposal ? (
        <button
          type="button"
          onClick={() => setViewerOpen(true)}
          onContextMenu={(e) => {
            e.preventDefault();
            setMenu({ x: e.clientX, y: e.clientY });
          }}
          title={tooltip}
          data-testid="proposal-chip"
          className="inline-flex max-w-[16rem] items-center gap-1.5 rounded-full bg-surface-secondary px-2.5 py-0.5 text-xs font-medium text-content-secondary transition-colors hover:bg-surface-tertiary hover:text-content-primary"
        >
          <FileText size={12} className="shrink-0 text-content-tertiary" />
          <span className="truncate">{proposal.filename}</span>
        </button>
      ) : canManage ? (
        <button
          type="button"
          onClick={pickFile}
          disabled={pending}
          data-testid="proposal-attach"
          className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-border px-2.5 py-0.5 text-xs text-content-tertiary transition-colors hover:border-oe-blue hover:text-oe-blue disabled:opacity-60"
        >
          {pending ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <Paperclip size={12} />
          )}
          {pending
            ? t('projects.proposal.uploading', { defaultValue: 'Uploading…' })
            : t('projects.proposal.attach', {
                defaultValue: 'Attach the original proposal',
              })}
        </button>
      ) : null}

      {error ? (
        <span
          role="alert"
          data-testid="proposal-error"
          className="text-2xs text-semantic-error"
        >
          {error}
        </span>
      ) : null}

      {/* ── Context menu (portalled, see the viewer above) ────────────── */}
      {menu && proposal && createPortal(
        <div
          ref={menuRef}
          role="menu"
          data-testid="proposal-menu"
          className="fixed z-[80] min-w-[11rem] rounded-lg border border-border-light bg-surface-elevated py-1 text-xs shadow-xl"
          style={{
            left: Math.min(menu.x, (typeof window !== 'undefined' ? window.innerWidth : 1280) - 200),
            top: Math.min(menu.y, (typeof window !== 'undefined' ? window.innerHeight : 800) - 180),
          }}
        >
          <button
            type="button"
            role="menuitem"
            className="block w-full px-3 py-1.5 text-left text-content-primary hover:bg-surface-secondary"
            onClick={() => {
              setMenu(null);
              setViewerOpen(true);
            }}
          >
            {t('projects.proposal.open', { defaultValue: 'Open' })}
          </button>
          <button
            type="button"
            role="menuitem"
            className="block w-full px-3 py-1.5 text-left text-content-primary hover:bg-surface-secondary"
            onClick={() => {
              setMenu(null);
              void downloadProtectedFile(downloadUrl, proposal.filename);
            }}
          >
            {t('files.actions.download', { defaultValue: 'Download' })}
          </button>
          <button
            type="button"
            role="menuitem"
            className="block w-full px-3 py-1.5 text-left text-content-primary hover:bg-surface-secondary"
            onClick={() => {
              setMenu(null);
              void openInNewTab();
            }}
          >
            {t('files.preview.open_new_tab', { defaultValue: 'Open in a new tab' })}
          </button>
          {canManage && (
            <>
              <button
                type="button"
                role="menuitem"
                className="block w-full px-3 py-1.5 text-left text-content-primary hover:bg-surface-secondary"
                onClick={() => {
                  setMenu(null);
                  pickFile();
                }}
              >
                {t('projects.proposal.replace', { defaultValue: 'Replace…' })}
              </button>
              <button
                type="button"
                role="menuitem"
                data-testid="proposal-menu-remove"
                className="block w-full border-t border-border-light px-3 py-1.5 text-left text-semantic-error hover:bg-surface-secondary"
                onClick={() => {
                  setMenu(null);
                  // Only the pointer is cleared. The uploaded document stays
                  // in the project's Documents, where it can be found again —
                  // detaching a proposal must not silently delete a file.
                  savePointer.mutate(null);
                }}
              >
                {t('projects.proposal.remove', { defaultValue: 'Remove' })}
              </button>
            </>
          )}
        </div>,
        document.body,
      )}

      {/* ── Viewer ───────────────────────────────────────────────────── */}
      {viewerOpen && proposal && isPdf(proposal.content_type, proposal.filename) &&
        // Portalled at the call site: the shared modal is written for callers
        // that are not inside a transformed ancestor, and the project header
        // card is. Moving its subtree to <body> restores viewport-relative
        // `position: fixed` without forking the component.
        createPortal(
          <InlinePdfPreviewModal
            open
            downloadUrl={downloadUrl}
            title={proposal.filename}
            onClose={() => setViewerOpen(false)}
          />,
          document.body,
        )}
      {viewerOpen && proposal && !isPdf(proposal.content_type, proposal.filename) && (
        <ProposalViewerModal
          proposal={proposal}
          downloadUrl={downloadUrl}
          onClose={() => setViewerOpen(false)}
        />
      )}
    </>
  );
}
