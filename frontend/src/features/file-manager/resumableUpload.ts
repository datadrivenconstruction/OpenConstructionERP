// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Resumable (chunked) upload client.
 *
 * Drives the backend ``/api/v1/resumable-uploads`` endpoints so a large
 * CAD / PDF file uploads in fixed-size chunks and survives a transient
 * network failure: a failed chunk is retried a few times, and if a session
 * was interrupted the client queries which chunks are still missing and
 * sends only those. On completion the backend assembles the file and hands
 * it to the same document store + conversion pipeline a single-shot upload
 * uses, so callers get an ordinary document back.
 *
 * Small files should NOT use this path - the caller is expected to keep the
 * single-shot multipart upload for anything under the threshold and only
 * reach for ``uploadResumable`` for large files.
 */

import { API_BASE, getAuthToken } from '@/shared/lib/api';

/** Default chunk size (8 MiB). Matches the backend default and the
 *  threshold above which the dialog switches to the chunked path. */
export const RESUMABLE_CHUNK_SIZE = 8 * 1024 * 1024;

/** Files at or above this size use the resumable path; smaller files fall
 *  back to the single-shot multipart upload. */
export const RESUMABLE_THRESHOLD_BYTES = 12 * 1024 * 1024;

/** How many times a single chunk PUT is retried on a transient failure
 *  before the whole upload is reported as failed (and offered for resume). */
const MAX_CHUNK_RETRIES = 4;

/** Base backoff between chunk retries (ms); grows linearly per attempt. */
const RETRY_BACKOFF_MS = 800;

interface SessionResponse {
  id: string;
  chunk_size: number;
  total_chunks: number;
  received_chunks: number[];
  missing_chunks: number[];
  status: string;
}

interface CompleteResponse {
  session_id: string;
  document_id: string;
  filename: string;
  file_size: number;
  status: string;
}

export interface ResumableUploadOptions {
  projectId: string;
  category: string;
  /** Called with a 0..100 integer whenever progress advances. */
  onProgress?: (percent: number) => void;
  /** AbortSignal to cancel the upload (also aborts the in-flight chunk). */
  signal?: AbortSignal;
}

export interface ResumableUploadResult {
  documentId: string;
  filename: string;
  fileSize: number;
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { 'X-DDC-Client': 'OE/1.0', ...extra };
  const token = getAuthToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return headers;
}

/** Compute the SHA-256 of a file as lower-case hex, or null when the Web
 *  Crypto subtle API is unavailable (e.g. insecure context). The backend
 *  treats the hash as optional; when present it verifies the assembled
 *  file against it. */
async function sha256Hex(file: File): Promise<string | null> {
  try {
    if (!crypto?.subtle) return null;
    const buf = await file.arrayBuffer();
    const digest = await crypto.subtle.digest('SHA-256', buf);
    return Array.from(new Uint8Array(digest))
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('');
  } catch {
    // Hashing a very large file can throw on memory pressure; degrade to
    // no client hash rather than failing the upload. The size check on the
    // server still guards integrity.
    return null;
  }
}

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Upload one chunk with bounded retries. Throws once retries are
 *  exhausted so the caller can surface a resumable error. */
async function putChunk(
  sessionId: string,
  index: number,
  body: Blob,
  signal?: AbortSignal,
): Promise<void> {
  let lastError: unknown = null;
  for (let attempt = 0; attempt < MAX_CHUNK_RETRIES; attempt += 1) {
    if (signal?.aborted) throw new DOMException('Upload aborted', 'AbortError');
    try {
      const res = await fetch(
        `${API_BASE}/v1/resumable-uploads/sessions/${sessionId}/chunks/${index}/`,
        {
          method: 'PUT',
          headers: authHeaders({ 'Content-Type': 'application/octet-stream' }),
          body,
          signal,
        },
      );
      if (res.ok) return;
      // 4xx other than 429 is a permanent error (bad index/size) - do not
      // retry, the upload is misconfigured.
      if (res.status >= 400 && res.status < 500 && res.status !== 429) {
        let detail = `chunk ${index} rejected (${res.status})`;
        try {
          const j = await res.json();
          if (j?.detail) detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
        } catch {
          /* keep default */
        }
        throw new Error(detail);
      }
      lastError = new Error(`chunk ${index} failed with ${res.status}`);
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') throw err;
      lastError = err;
    }
    // Linear backoff before the next attempt.
    await delay(RETRY_BACKOFF_MS * (attempt + 1));
  }
  throw lastError instanceof Error ? lastError : new Error(`chunk ${index} failed`);
}

/** Read a failed complete response once: its message, and any resumable gap.
 *
 * A 409 from complete carries ``{error, missing_chunks}``. Reading the body a
 * second time throws, so both facts are pulled out in one pass and the caller
 * decides whether to resend or give up. */
async function readCompleteFailure(
  res: Response,
): Promise<{ detail: string; missing: number[] }> {
  const fallback = `failed to finalize upload (${res.status})`;
  try {
    const body = await res.json();
    const detail = body?.detail;
    if (typeof detail === 'string') return { detail, missing: [] };
    if (detail && typeof detail === 'object') {
      const raw = (detail as { missing_chunks?: unknown }).missing_chunks;
      const missing = Array.isArray(raw)
        ? raw.filter((n): n is number => typeof n === 'number' && Number.isInteger(n))
        : [];
      return { detail: JSON.stringify(detail), missing };
    }
    return { detail: fallback, missing: [] };
  } catch {
    return { detail: fallback, missing: [] };
  }
}

/** Upload a large file in resumable chunks and return the created document.
 *
 * The flow: create a session, send each still-missing chunk (retrying
 * transient failures), then call complete to assemble + convert. If the
 * server already had some chunks (a resumed session id is not surfaced to
 * callers here, so this always starts fresh), only missing chunks are sent.
 */
export async function uploadResumable(
  file: File,
  options: ResumableUploadOptions,
): Promise<ResumableUploadResult> {
  const { projectId, category, onProgress, signal } = options;

  const sha = await sha256Hex(file);

  // 1. Create the session.
  const createRes = await fetch(`${API_BASE}/v1/resumable-uploads/sessions/`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      project_id: projectId,
      filename: file.name,
      total_size: file.size,
      chunk_size: RESUMABLE_CHUNK_SIZE,
      category,
      sha256: sha,
    }),
    signal,
  });
  if (!createRes.ok) {
    let detail = `failed to start upload (${createRes.status})`;
    try {
      const j = await createRes.json();
      if (j?.detail) detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  const session = (await createRes.json()) as SessionResponse;
  const chunkSize = session.chunk_size || RESUMABLE_CHUNK_SIZE;
  const totalChunks = session.total_chunks;

  // 2. Send the still-missing chunks. ``missing_chunks`` on a fresh session
  //    is the full range; on a resume it would be only the gaps.
  const missing = session.missing_chunks?.length
    ? session.missing_chunks
    : Array.from({ length: totalChunks }, (_, i) => i);

  let done = totalChunks - missing.length;
  const report = () => onProgress?.(Math.min(99, Math.round((done / totalChunks) * 100)));
  report();

  const sendChunks = async (indices: number[]): Promise<void> => {
    for (const index of indices) {
      if (signal?.aborted) throw new DOMException('Upload aborted', 'AbortError');
      const start = index * chunkSize;
      const end = Math.min(file.size, start + chunkSize);
      const blob = file.slice(start, end);
      await putChunk(session.id, index, blob, signal);
      done += 1;
      report();
    }
  };

  await sendChunks(missing);

  // 3. Assemble + hand off to the document pipeline.
  const requestComplete = () =>
    fetch(`${API_BASE}/v1/resumable-uploads/sessions/${session.id}/complete/`, {
      method: 'POST',
      headers: authHeaders(),
      signal,
    });

  let completeRes = await requestComplete();
  let failure = completeRes.ok ? null : await readCompleteFailure(completeRes);

  // A refusal that names the chunks the server could not read means its
  // scratch copies were lost between upload and assembly, not that the file is
  // bad. The server has already forgotten exactly those chunks, so resending
  // them and asking again is the whole recovery, and it costs the gap rather
  // than the file. Retried once: a second refusal means something is dropping
  // chunks faster than we can replace them, and looping would only hide it.
  if (failure && failure.missing.length > 0) {
    done = Math.max(0, done - failure.missing.length);
    report();
    await sendChunks(failure.missing);
    completeRes = await requestComplete();
    failure = completeRes.ok ? null : await readCompleteFailure(completeRes);
  }

  if (failure) throw new Error(failure.detail);
  const result = (await completeRes.json()) as CompleteResponse;
  onProgress?.(100);
  return {
    documentId: result.document_id,
    filename: result.filename,
    fileSize: result.file_size,
  };
}
