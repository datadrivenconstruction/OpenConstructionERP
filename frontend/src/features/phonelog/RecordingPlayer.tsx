// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Plays back a stored call recording. Two modes: pass `src` (an object URL the
// caller owns, used right after upload so playback is instant) to render the
// player immediately, or pass `id` to lazy-fetch the recording as an
// authenticated blob on first click. Kept small so both the review panel and the
// saved-record card can reuse it.

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Play } from 'lucide-react';
import { fetchRecordingBlob } from './api';

interface RecordingPlayerProps {
  id?: string;
  src?: string;
  label?: string;
}

export function RecordingPlayer({ id, src, label }: RecordingPlayerProps) {
  const { t } = useTranslation();
  const [url, setUrl] = useState<string | null>(src ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const objectUrlRef = useRef<string | null>(null);

  useEffect(() => {
    if (src) setUrl(src);
  }, [src]);

  // Only revoke object URLs this component created (never the caller-owned src).
  useEffect(
    () => () => {
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    },
    [],
  );

  const load = useCallback(async () => {
    if (url || !id) return;
    setLoading(true);
    setError(false);
    try {
      const blob = await fetchRecordingBlob(id);
      const objUrl = URL.createObjectURL(blob);
      objectUrlRef.current = objUrl;
      setUrl(objUrl);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [id, url]);

  if (url) {
    return <audio src={url} controls className="w-full" />;
  }

  if (error) {
    return (
      <p className="text-xs text-content-tertiary">
        {t('phonelog.rec.no_audio', { defaultValue: 'The recording could not be loaded for playback.' })}
      </p>
    );
  }

  return (
    <button
      type="button"
      onClick={load}
      disabled={loading}
      className="inline-flex items-center gap-1.5 rounded-md border border-border-light px-2 py-1 text-xs text-content-secondary hover:bg-surface-secondary disabled:cursor-not-allowed disabled:opacity-50"
    >
      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
      {label ?? t('phonelog.rec.play', { defaultValue: 'Play recording' })}
    </button>
  );
}
