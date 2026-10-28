// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// API client for the shared voice-capture flow. One call, POST /voice/draft,
// turns a recording OR a transcript plus a target type into a structured draft.
// A raw multipart fetch is used (like the phone-log recording upload) so the
// auth header is attached and the optional file rides alongside the transcript
// field; apiPost would force a JSON content-type and break the boundary.

import { getAuthToken } from '@/shared/lib/api';
import type { VoiceDraft, VoiceTargetType } from './types';


export interface VoiceDraftOptions {
  /** Audio/video recording of the spoken note. Omit to structure typed text. */
  file?: File;
  /** Typed or edited note text. Used when no file is sent (or as a fallback). */
  transcript?: string;
  /** UI locale the draft should be written in (translates the note). */
  targetLanguage?: string;
  /** Abort signal so an in-flight request can be cancelled on unmount/cancel. */
  signal?: AbortSignal;
}

/** List the target types the backend can structure a note into. */
export async function fetchVoiceTargets(): Promise<string[]> {
  const token = getAuthToken();
  const res = await fetch(`/api/v1/voice/targets`, {
    headers: { 'X-DDC-Client': 'OE/1.0', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!res.ok) throw new Error(`Could not load voice targets (${res.status})`);
  return (await res.json()) as string[];
}

/**
 * Turn a recording or a transcript into a structured draft for review.
 *
 * Sends multipart form data: the query string carries the project, target type
 * and working language; the body carries the optional recording and/or the
 * transcript text. Returns the draft the UI presents for human confirmation.
 */
export async function requestVoiceDraft(
  projectId: string,
  target: VoiceTargetType,
  opts: VoiceDraftOptions,
): Promise<VoiceDraft> {
  const params = new URLSearchParams({ project_id: projectId, target_type: target });
  if (opts.targetLanguage) params.set('target_language', opts.targetLanguage);

  const form = new FormData();
  if (opts.file) form.append('file', opts.file);
  // Always send the transcript field (empty string is fine) so the endpoint's
  // multipart body is well-formed even on the file-only path.
  form.append('transcript', opts.transcript ?? '');

  const token = getAuthToken();
  const res = await fetch(`/api/v1/voice/draft?${params.toString()}`, {
    method: 'POST',
    headers: { 'X-DDC-Client': 'OE/1.0', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: form,
    signal: opts.signal,
  });
  if (!res.ok) {
    let detail = `Could not process the note (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      // response was not JSON; keep the generic message
    }
    throw new Error(detail);
  }
  return (await res.json()) as VoiceDraft;
}
