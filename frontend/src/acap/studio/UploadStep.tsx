import { useCallback, useEffect, useRef, useState } from 'react';
import { Upload, Loader2, AlertTriangle } from 'lucide-react';
import { getErrorMessage, ApiError } from '@/shared/lib/api';
import { uploadPlanImage, extractPlanImage, isVisionNotConfiguredError, type ExtractResponse } from './studioApi';

const ACCEPT = '.png,.jpg,.jpeg,.webp,.pdf';
const UPLOAD_TIMEOUT_MS = 60_000;

type UploadState =
  | { status: 'idle' }
  | { status: 'uploading' }
  | { status: 'extracting' }
  | { status: 'done'; result: ExtractResponse }
  | { status: 'not-configured' }
  | { status: 'error'; message: string };

interface UploadStepProps {
  projectId: string;
  onExtracted: (result: ExtractResponse) => void;
}

export function UploadStep({ projectId, onExtracted }: UploadStepProps) {
  const [state, setState] = useState<UploadState>({ status: 'idle' });
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setSelectedFile(file);
    setPreview(file.type.startsWith('image/') ? URL.createObjectURL(file) : null);
    setState({ status: 'idle' });
  }, []);

  // Revoke the previous object URL when preview changes or on unmount (no leak).
  useEffect(() => {
    if (!preview) return;
    return () => URL.revokeObjectURL(preview);
  }, [preview]);

  const handleUploadExtract = useCallback(async () => {
    if (!selectedFile) return;
    const ctrl = new AbortController();
    controllerRef.current = ctrl;
    const timeoutId = setTimeout(() => ctrl.abort(), UPLOAD_TIMEOUT_MS);

    setState({ status: 'uploading' });
    try {
      const upload = await uploadPlanImage(projectId, selectedFile, ctrl.signal);
      clearTimeout(timeoutId);
      setState({ status: 'extracting' });

      const extract = await extractPlanImage(projectId, upload.image_id);
      setState({ status: 'done', result: extract });
      onExtracted(extract);
    } catch (err) {
      clearTimeout(timeoutId);
      if (isVisionNotConfiguredError(err)) {
        setState({ status: 'not-configured' });
      } else {
        setState({ status: 'error', message: getErrorMessage(err) });
      }
    }
  }, [selectedFile, projectId, onExtracted]);

  const isProcessing = state.status === 'uploading' || state.status === 'extracting';

  return (
    <div className="flex flex-col gap-4">
      <input
        ref={fileRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={handleFileSelect}
      />

      <div
        onClick={() => fileRef.current?.click()}
        className="flex cursor-pointer flex-col items-center gap-2 rounded-lg border-2 border-dashed border-border p-8 hover:border-oe-blue"
      >
        {preview ? (
          <img src={preview} alt="Preview" className="max-h-48 rounded-md object-contain" />
        ) : (
          <>
            <Upload size={24} className="text-content-secondary" />
            <span className="text-sm text-content-secondary">
              {selectedFile ? selectedFile.name : 'Klik untuk pilih gambar denah (PNG/JPG/WebP/PDF)'}
            </span>
          </>
        )}
      </div>

      <button
        type="button"
        onClick={handleUploadExtract}
        disabled={!selectedFile || isProcessing}
        className="inline-flex items-center justify-center gap-2 rounded-md bg-oe-blue px-4 py-2 text-sm font-medium text-white hover:bg-oe-blue-hover disabled:opacity-50"
      >
        {isProcessing && <Loader2 size={16} className="animate-spin" />}
        {state.status === 'uploading' && 'Mengunggah…'}
        {state.status === 'extracting' && 'AI Extract…'}
        {!isProcessing && 'Upload & Extract'}
      </button>

      {state.status === 'not-configured' && (
        <div className="rounded-md border border-border bg-surface-secondary p-4 text-sm text-content-secondary">
          Vision belum dikonfigurasi — set GOOGLE_API_KEY di .env lalu restart backend.
        </div>
      )}

      {state.status === 'error' && (
        <div className="text-sm text-semantic-error">{state.message}</div>
      )}

      {state.status === 'done' && !state.result.valid && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <div className="flex items-start gap-2">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <div>
              <p className="font-medium">Perlu dirapikan di langkah Konfirmasi:</p>
              <ul className="mt-1 list-disc pl-5">
                {state.result.reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default UploadStep;
