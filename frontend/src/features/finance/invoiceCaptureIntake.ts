// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** Where a capture came from; mirrors the backend `CAPTURE_SOURCES`. */
export type CaptureSource = 'upload' | 'camera' | 'email';

const KNOWN_SOURCES: readonly string[] = ['upload', 'camera', 'email'];

/** Normalise a server value so an unknown source still renders as a plain upload. */
export function captureSourceOf(value: string | null | undefined): CaptureSource {
  return KNOWN_SOURCES.includes(value ?? '') ? (value as CaptureSource) : 'upload';
}

const CAPTURABLE_EXT = /\.(pdf|png|jpe?g|gif|webp|heic|heif|xml)$/i;

/** True for the file kinds the capture inbox accepts (PDF, image, e-invoice XML). */
export function isCapturable(file: { name: string; type: string }): boolean {
  if (file.type === 'application/pdf' || file.type.startsWith('image/')) return true;
  if (file.type === 'application/xml' || file.type === 'text/xml') return true;
  return CAPTURABLE_EXT.test(file.name);
}

export interface BatchOutcome<T> {
  captured: T[];
  failed: Array<{ name: string; message: string }>;
  skipped: string[];
}

/**
 * Upload files one after another so a slow extraction never floods the server and
 * one bad file never loses the rest. Unsupported files are reported, not sent.
 */
export async function uploadBatch<T>(
  files: Array<File>,
  upload: (file: File) => Promise<T>,
): Promise<BatchOutcome<T>> {
  const out: BatchOutcome<T> = { captured: [], failed: [], skipped: [] };
  for (const file of files) {
    if (!isCapturable(file)) {
      out.skipped.push(file.name);
      continue;
    }
    try {
      out.captured.push(await upload(file));
    } catch (e) {
      out.failed.push({ name: file.name, message: e instanceof Error ? e.message : String(e) });
    }
  }
  return out;
}
