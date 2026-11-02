// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Drop or pick photos; on a phone the picker opens the rear camera and the fix is sent along.

import { useRef, useState, type DragEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Camera, Loader2, Upload } from 'lucide-react';
import { captureDeviceEvidence } from '@/shared/lib/photoEvidence';
import { useToastStore } from '@/stores/useToastStore';
import { photosKeys, uploadPhotos, type TargetKind, type UploadResult } from '../api';

interface PhotoUploadDropzoneProps {
  projectId: string;
  target?: { kind: TargetKind; id: string };
  compact?: boolean;
  onUploaded?: (result: UploadResult) => void;
}

const MAX_FILES = 50;

export function PhotoUploadDropzone({ projectId, target, compact, onUploaded }: PhotoUploadDropzoneProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const input = useRef<HTMLInputElement | null>(null);
  const [over, setOver] = useState(false);

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      // A fix taken now describes where the person stands; it is only a hint for files shot elsewhere.
      const device = await captureDeviceEvidence();
      return uploadPhotos(projectId, files, { device, target });
    },
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: photosKeys.all });
      if (result.items.length) {
        addToast({ type: 'success', title: t('photoArchive.upload.done', { count: result.items.length }) });
      }
      for (const err of result.errors) {
        addToast({ type: 'error', title: t('photoArchive.upload.file_failed', { name: err.filename }), message: err.error });
      }
      onUploaded?.(result);
    },
    onError: (err: Error) => addToast({ type: 'error', title: t('photoArchive.upload.failed'), message: err.message }),
  });

  const send = (list: FileList | null) => {
    const files = Array.from(list ?? []).filter((f) => f.type.startsWith('image/') || /\.(heic|heif)$/i.test(f.name));
    if (!files.length) return;
    if (files.length > MAX_FILES) {
      addToast({ type: 'warning', title: t('photoArchive.upload.too_many', { count: MAX_FILES }) });
    }
    upload.mutate(files.slice(0, MAX_FILES));
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setOver(false);
    send(e.dataTransfer.files);
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={`flex items-center gap-3 rounded-lg border-2 border-dashed transition-colors ${
        over ? 'border-oe-blue bg-oe-blue/5' : 'border-border-light'
      } ${compact ? 'px-3 py-2' : 'flex-col justify-center px-4 py-6 text-center'}`}
    >
      <input
        ref={input}
        type="file"
        accept="image/*"
        capture="environment"
        multiple
        className="hidden"
        data-testid="photo-upload-input"
        onChange={(e) => {
          send(e.target.files);
          e.target.value = '';
        }}
      />
      {upload.isPending ? (
        <Loader2 className="h-5 w-5 animate-spin text-oe-blue" aria-hidden />
      ) : compact ? (
        <Camera className="h-5 w-5 text-content-tertiary" aria-hidden />
      ) : (
        <Upload className="h-6 w-6 text-content-tertiary" aria-hidden />
      )}
      <div className={compact ? 'text-xs text-content-secondary' : 'text-sm text-content-secondary'}>
        {upload.isPending ? t('photoArchive.upload.sending') : t('photoArchive.upload.hint')}
      </div>
      <button
        type="button"
        disabled={upload.isPending}
        onClick={() => input.current?.click()}
        className="rounded-md bg-oe-blue px-3 py-1.5 text-xs font-medium text-white hover:bg-oe-blue/90 disabled:opacity-50"
      >
        {t('photoArchive.upload.pick')}
      </button>
    </div>
  );
}
