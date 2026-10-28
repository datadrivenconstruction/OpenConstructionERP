// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Photo evidence of one defect notice.
 *
 * The files live in the project photo gallery (category "defect"); the defect
 * keeps each photo's gallery id and its evidence record. A photo taken with the
 * camera button carries the device position, clock and direction; an uploaded
 * file carries what its camera stored.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Camera, ImageOff, Loader2, Trash2, Upload } from 'lucide-react';
import { Button } from '@/shared/ui';
import { EvidenceBadge } from '@/shared/ui/EvidenceBadge';
import { API_BASE, fetchWithAuth } from '@/shared/lib/api';
import { captureDeviceEvidence, type DeviceCapture } from '@/shared/lib/photoEvidence';
import { useToastStore } from '@/stores/useToastStore';
import { removeDefectPhoto, uploadDefectPhoto, type Defect } from './api';

function useGalleryImage(photoId: string | undefined): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!photoId) return;
    let objectUrl: string | null = null;
    let cancelled = false;
    fetchWithAuth(`${API_BASE}/v1/documents/photos/${photoId}/file/`)
      .then((res) => (res.ok ? res.blob() : null))
      .then((blob) => {
        if (cancelled || !blob) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [photoId]);
  return url;
}

function Thumb({ photoId, alt }: { photoId: string | undefined; alt: string }) {
  const url = useGalleryImage(photoId);
  return url ? (
    <img src={url} alt={alt} className="h-full w-full object-cover" />
  ) : (
    <div className="flex h-full w-full items-center justify-center">
      <ImageOff size={16} className="text-content-quaternary" />
    </div>
  );
}

export function DefectPhotosPanel({
  defect,
  projectId,
  onChanged,
}: {
  defect: Defect;
  projectId: string;
  onChanged: (updated: Defect) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const cameraRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const capturePromise = useRef<Promise<DeviceCapture> | null>(null);
  const photos = defect.photos ?? [];

  const uploadMut = useMutation({
    mutationFn: ({ file, capture }: { file: File; capture: DeviceCapture | null }) =>
      uploadDefectPhoto(projectId, defect.id, file, capture),
    onSuccess: onChanged,
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('defects_liability.photo_upload_failed', { defaultValue: 'Photo upload failed' }),
        message: e.message,
      }),
  });
  const removeMut = useMutation({
    mutationFn: (index: number) => removeDefectPhoto(projectId, defect.id, index),
    onSuccess: onChanged,
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const handle = useCallback(
    async (files: FileList | null, fromCamera: boolean) => {
      const pending = capturePromise.current;
      capturePromise.current = null;
      if (!files) return;
      const capture = fromCamera && pending ? await pending : null;
      for (const file of Array.from(files)) {
        try {
          await uploadMut.mutateAsync({ file, capture });
        } catch {
          // toasted by the mutation
        }
      }
    },
    [uploadMut],
  );

  return (
    <div className="space-y-2 bg-surface-secondary/50 px-4 py-3" data-testid={`defect-photos-${defect.id}`}>
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={cameraRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="sr-only"
          onChange={(e) => {
            void handle(e.target.files, true);
            e.target.value = '';
          }}
        />
        <Button
          variant="secondary"
          size="sm"
          icon={<Camera size={14} />}
          disabled={uploadMut.isPending}
          onClick={() => {
            capturePromise.current = captureDeviceEvidence();
            cameraRef.current?.click();
          }}
        >
          {t('punch.photo_take', { defaultValue: 'Camera' })}
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          multiple
          className="sr-only"
          onChange={(e) => {
            void handle(e.target.files, false);
            e.target.value = '';
          }}
        />
        <Button
          variant="secondary"
          size="sm"
          icon={uploadMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
          disabled={uploadMut.isPending}
          onClick={() => fileRef.current?.click()}
        >
          {t('punch.photo_upload', { defaultValue: 'Upload' })}
        </Button>
        <span className="text-2xs text-content-tertiary">
          {t('field_evidence.camera_hint', {
            defaultValue:
              'Camera photos record your position (if you allow it), the time and the direction as evidence. Uploaded files keep the location and time stored by the camera.',
          })}
        </span>
      </div>
      {photos.length === 0 ? (
        <p className="text-xs text-content-tertiary">
          {t('defects_liability.photos_empty', {
            defaultValue: 'No photos yet. Photograph the defect when it is notified and again once it is rectified.',
          })}
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {photos.map((photo, index) => (
            <div key={`${photo.photo_id}-${index}`} className="overflow-hidden rounded-lg border border-border-light bg-surface-primary">
              <div className="relative aspect-video bg-surface-secondary">
                <Thumb
                  photoId={photo.photo_id}
                  alt={t('defects_liability.photo_alt', {
                    defaultValue: 'Defect {{reference}} photo {{n}}',
                    reference: defect.reference,
                    n: index + 1,
                  })}
                />
                <button
                  type="button"
                  className="absolute right-1 top-1 inline-flex h-6 w-6 items-center justify-center rounded-md bg-black/50 text-white hover:bg-black/70"
                  aria-label={t('punch.photo_delete', { defaultValue: 'Delete photo' })}
                  onClick={() => removeMut.mutate(index)}
                  disabled={removeMut.isPending}
                >
                  <Trash2 size={12} />
                </button>
              </div>
              <div className="p-2">
                <EvidenceBadge evidence={photo.evidence ?? null} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
