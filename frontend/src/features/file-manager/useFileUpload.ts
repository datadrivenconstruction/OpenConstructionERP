// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Shared upload routine for the file manager.
 *
 * Extracted from ``UploadDialog`` so the same ``doUpload`` path can drive
 * both the dialog and the page-level drag-and-drop drop zone. Routes each
 * upload to the endpoint that owns its kind so files land in the right
 * pipeline instead of all becoming generic documents:
 *   - BIM models (RVT / IFC / ...) -> POST /api/v1/bim_hub/upload-cad/
 *   - DWG / DXF drawings           -> POST /api/v1/dwg_takeoff/drawings/upload/
 *   - site photos                  -> POST /api/v1/documents/photos/upload/
 *   - everything else              -> POST /api/v1/documents/upload/
 * Large document uploads take the resumable chunked client; the dedicated
 * BIM/DWG/photo endpoints stream server-side. Progress rolls up into the
 * same FloatingQueuePanel used everywhere else.
 */

import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { uuid } from '@/shared/lib/browser';
import { extractErrorMessageFromBody } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useUploadQueueStore } from '@/stores/useUploadQueueStore';
import { fileManagerKeys } from './hooks';
import { uploadResumable, RESUMABLE_THRESHOLD_BYTES } from './resumableUpload';
import type { FileKind } from './types';
// Name-only mesh check (three.js-free) so recognising a 3D file here does not
// pull the BIM viewer's loader graph into the file-manager bundle.
import { isMeshImportFile } from '@/features/bim/meshImport/formats';

/** Map FileKind -> documents-module category. Used only by the documents
 * pipeline (the kinds that don't have a dedicated endpoint). */
function categoryForKind(kind: FileKind | null): string {
  if (kind === 'photo') return 'photo';
  if (kind === 'sheet') return 'drawing';
  return 'other';
}

export interface UseFileUploadResult {
  /** Upload the given files into the pipeline for ``kind``. ``onDone`` runs
   *  once the batch has been queued (not once each transfer finishes). */
  doUpload: (files: FileList | File[], kind: FileKind | null, onDone?: () => void) => Promise<void>;
  uploading: boolean;
}

export function useFileUpload(projectId: string | null | undefined): UseFileUploadResult {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const addQueueTask = useUploadQueueStore((s) => s.addTask);
  const updateQueueTask = useUploadQueueStore((s) => s.updateTask);
  const [uploading, setUploading] = useState(false);

  // Resolve where a kind's upload should go. ``bim_model`` and
  // ``dwg_drawing`` have their own ingest endpoints (and their own storage +
  // conversion pipelines); site photos go to the photo pipeline so a real
  // ProjectPhoto is created; everything else stays on the documents endpoint.
  const directUploadUrl = useCallback(
    (kind: FileKind | null): string | null => {
      if (kind === 'bim_model') {
        return `/api/v1/bim_hub/upload-cad/?project_id=${projectId}`;
      }
      if (kind === 'dwg_drawing') {
        return `/api/v1/dwg_takeoff/drawings/upload/?project_id=${projectId}`;
      }
      if (kind === 'photo') {
        return `/api/v1/documents/photos/upload/?project_id=${projectId}`;
      }
      return null;
    },
    [projectId],
  );

  const doUpload = useCallback(
    async (files: FileList | File[], kind: FileKind | null, onDone?: () => void) => {
      if (!projectId) {
        addToast({
          type: 'error',
          title: t('files.upload_no_project', { defaultValue: 'No active project' }),
        });
        return;
      }

      const validFiles = Array.from(files);
      if (validFiles.length === 0) return;

      const token = useAuthStore.getState().accessToken;
      const cat = categoryForKind(kind);
      // Non-null for BIM/DWG/photo kinds -> upload goes straight to that
      // module's ingest endpoint (single-shot, server-streamed) instead of
      // the documents pipeline / resumable client.
      const directUrl = directUploadUrl(kind);
      setUploading(true);

      // Count 3D mesh files in the batch so we can nudge the user toward the
      // BIM Hub 3D uploader (which actually views/measures them) after queuing.
      let meshCount = 0;

      for (const file of validFiles) {
        // Common 3D mesh formats (OBJ/STL/glTF/GLB/DAE/FBX/PLY/3DS/…) are not
        // server-convertible CAD: the raw-CAD ingest endpoint would reject
        // them (400). Keep them on the documents pipeline so they are stored
        // safely as a file, and point the user to the BIM Hub 3D uploader to
        // actually view and measure them.
        const isMesh = isMeshImportFile(file.name);
        if (isMesh) meshCount += 1;
        const fileDirectUrl = isMesh ? null : directUrl;
        const taskId = uuid();
        addQueueTask({
          id: taskId,
          type: 'file_upload',
          filename: file.name,
          status: 'processing',
          progress: 0,
          message: t('files.uploading', { defaultValue: 'Uploading…' }),
        });

        // Fire-and-forget — same pattern as DocumentsPage so progress shows
        // up in the global FloatingQueuePanel.
        (async () => {
          const markDone = () => {
            updateQueueTask(taskId, {
              status: 'completed',
              progress: 100,
              message: t('files.uploaded', { defaultValue: 'Uploaded' }),
              completedAt: Date.now(),
            });
            queryClient.invalidateQueries({ queryKey: [fileManagerKeys.tree, projectId] });
            queryClient.invalidateQueries({ queryKey: [fileManagerKeys.list, projectId] });
            if (kind === 'photo') {
              queryClient.invalidateQueries({
                predicate: (q) =>
                  q.queryKey.some(
                    (k) => typeof k === 'string' && k.toLowerCase().includes('photo'),
                  ),
              });
            }
          };
          const markError = (detail: string) => {
            updateQueueTask(taskId, {
              status: 'error',
              error: detail,
              completedAt: Date.now(),
            });
          };

          // Large document files take the resumable, chunked path: real
          // progress and per-chunk retry. Small files keep the single-shot
          // multipart upload. BIM/DWG/photo always take the single-shot path
          // to their own endpoint (which streams server-side regardless).
          if (!fileDirectUrl && file.size >= RESUMABLE_THRESHOLD_BYTES) {
            try {
              updateQueueTask(taskId, {
                message: t('files.uploading_chunked', {
                  defaultValue: 'Uploading large file…',
                }),
              });
              await uploadResumable(file, {
                projectId,
                category: cat,
                onProgress: (percent) => updateQueueTask(taskId, { progress: percent }),
              });
              markDone();
            } catch (err) {
              markError(
                err instanceof Error
                  ? err.message
                  : t('files.upload_resume_failed', {
                      defaultValue: 'Upload interrupted. Try again to resume.',
                    }),
              );
            }
            return;
          }

          try {
            const formData = new FormData();
            formData.append('file', file);

            const headers: Record<string, string> = { 'X-DDC-Client': 'OE/1.0' };
            if (token) headers['Authorization'] = `Bearer ${token}`;

            const estimatedMs = Math.max(2000, (file.size / (1024 * 1024)) * 500);
            const progressTimer = setInterval(() => {
              const task = useUploadQueueStore.getState().tasks.find((tk) => tk.id === taskId);
              if (task && task.status === 'processing' && task.progress < 90) {
                updateQueueTask(taskId, { progress: task.progress + 5 });
              }
            }, estimatedMs / 18);

            const res = await fetch(
              fileDirectUrl ?? `/api/v1/documents/upload/?project_id=${projectId}&category=${cat}`,
              { method: 'POST', headers, body: formData },
            );

            clearInterval(progressTimer);

            if (!res.ok) {
              let detail = file.name;
              try {
                const body = await res.json();
                detail = extractErrorMessageFromBody(body) ?? detail;
              } catch {
                /* ignore — keep filename */
              }
              markError(detail);
            } else {
              markDone();
            }
          } catch (err) {
            markError(err instanceof Error ? err.message : 'Upload failed');
          }
        })();
      }

      addToast({
        type: 'info',
        title: t('files.upload_queued', {
          defaultValue: '{{count}} file(s) queued',
          count: validFiles.length,
        }),
      });

      // 3D mesh files are stored here as documents, but the place to actually
      // view and measure them is the BIM Hub 3D uploader (it reads OBJ/STL/
      // glTF/… in the browser). Surface that once per batch, not per file.
      if (meshCount > 0) {
        addToast({
          type: 'info',
          title: t('files.mesh_saved_title', {
            defaultValue: '3D mesh saved',
          }),
          message: t('files.mesh_saved_hint', {
            defaultValue:
              'Open the BIM Hub 3D uploader and drop the file there to view, measure and extract geometry quantities.',
          }),
        });
      }

      setUploading(false);
      onDone?.();
    },
    [projectId, directUploadUrl, addToast, addQueueTask, updateQueueTask, queryClient, t],
  );

  return { doUpload, uploading };
}
