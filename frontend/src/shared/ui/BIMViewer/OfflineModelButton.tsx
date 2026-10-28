// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Save for offline" control for the fast BIM viewer.
 *
 * On a construction site the network drops. This button downloads a model's
 * streaming geometry tiles into the device's local cache ahead of time, so the
 * model then opens fully with no signal - the "prep it in the office, walk it on
 * site" story. It only appears for models that have a streamable tileset, shows
 * how much it is about to save, streams live progress, and can be cancelled by
 * clicking again. It writes to the same content-addressed cache the streaming
 * loader reads, so a saved model is served entirely from cache on the next open.
 *
 * Self-contained: give it a modelId, drop it in a toolbar. It cancels its own
 * work on unmount and re-probes when the model changes.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { AlertCircle, Check, Download, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { fetchTileManifest, prefetchModelTiles } from './streaming/tileStreamer';
import { fmtFixed } from '@/shared/lib/formatters';

type Phase = 'probing' | 'unavailable' | 'idle' | 'saving' | 'saved' | 'error';

interface OfflineModelButtonProps {
  modelId: string;
  className?: string;
}

/** Human-readable byte size, e.g. 12 MB. Empty string for unknown sizes. */
function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = n;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const rounded = value < 10 && unit > 0 ? fmtFixed(value, 1) : String(Math.round(value));
  return `${rounded} ${units[unit]}`;
}

export function OfflineModelButton({ modelId, className }: OfflineModelButtonProps) {
  const { t } = useTranslation();
  const [phase, setPhase] = useState<Phase>('probing');
  const [percent, setPercent] = useState(0);
  const [totalBytes, setTotalBytes] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  // The model this button currently represents. A save started for one model
  // must not flip the phase after the user has switched the picker to another.
  const latestModelIdRef = useRef(modelId);

  // Probe once per model: does it have a downloadable tileset, and how big?
  // Models without tiles (the monolithic-GLB fallback) simply hide the button.
  useEffect(() => {
    latestModelIdRef.current = modelId;
    setPhase('probing');
    setPercent(0);
    setTotalBytes(0);
    const controller = new AbortController();
    let alive = true;
    fetchTileManifest(modelId, controller.signal)
      .then((m) => {
        if (!alive) return;
        if (m && m.tiles.length > 0) {
          setTotalBytes(m.total_bytes ?? 0);
          setPhase('idle');
        } else {
          setPhase('unavailable');
        }
      })
      .catch(() => {
        if (alive) setPhase('unavailable');
      });
    return () => {
      alive = false;
      controller.abort();
    };
  }, [modelId]);

  // Cancel any in-flight save if the button unmounts.
  useEffect(() => () => abortRef.current?.abort(), []);

  const handleClick = useCallback(async () => {
    // A click while saving cancels; the cleanup path resets to idle.
    if (phase === 'saving') {
      abortRef.current?.abort();
      return;
    }
    const myModel = modelId;
    const controller = new AbortController();
    abortRef.current = controller;
    setPhase('saving');
    setPercent(0);
    try {
      const result = await prefetchModelTiles(modelId, {
        signal: controller.signal,
        onProgress: ({ done, total }) => {
          if (total > 0 && latestModelIdRef.current === myModel) {
            setPercent(Math.round((done / total) * 100));
          }
        },
      });
      // The picker moved to another model while this ran: leave that model's
      // button state to its own probe rather than overwriting it.
      if (latestModelIdRef.current !== myModel) return;
      if (controller.signal.aborted) {
        setPhase('idle');
        return;
      }
      if (!result) {
        setPhase('unavailable');
        return;
      }
      // Some tiles fetched -> a usable offline copy exists (partial is fine).
      // Nothing fetched at all -> a genuine failure worth retrying.
      setPhase(result.ok > 0 ? 'saved' : 'error');
    } catch {
      if (latestModelIdRef.current === myModel && !controller.signal.aborted) {
        setPhase('error');
      }
    }
  }, [modelId, phase]);

  if (phase === 'probing' || phase === 'unavailable') return null;

  const sizeLabel = formatBytes(totalBytes);
  const base =
    'flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-sm transition-colors';

  if (phase === 'saving') {
    return (
      <button
        type="button"
        onClick={handleClick}
        className={`${base} border-border-light text-content-secondary hover:bg-surface-secondary ${className ?? ''}`}
        title={t('bim.offline_cancel_hint', { defaultValue: 'Downloading - click to cancel' })}
      >
        <Loader2 size={15} className="animate-spin" />
        {t('bim.offline_saving', { percent, defaultValue: 'Saving {{percent}}%' })}
      </button>
    );
  }

  if (phase === 'saved') {
    return (
      <button
        type="button"
        onClick={handleClick}
        className={`${base} border-emerald-500/40 text-emerald-600 hover:bg-emerald-500/10 dark:text-emerald-400 ${className ?? ''}`}
        title={t('bim.offline_saved_hint', {
          defaultValue:
            'This model is saved on this device and opens without a network. Click to refresh.',
        })}
      >
        <Check size={15} />
        {t('bim.offline_saved', { defaultValue: 'Saved for offline' })}
      </button>
    );
  }

  if (phase === 'error') {
    return (
      <button
        type="button"
        onClick={handleClick}
        className={`${base} border-rose-500/40 text-rose-600 hover:bg-rose-500/10 dark:text-rose-400 ${className ?? ''}`}
        title={t('bim.offline_error_hint', {
          defaultValue: 'The download did not finish. Check the connection and try again.',
        })}
      >
        <AlertCircle size={15} />
        {t('bim.offline_retry', { defaultValue: 'Save failed, retry' })}
      </button>
    );
  }

  // idle
  return (
    <button
      type="button"
      onClick={handleClick}
      className={`${base} border-border-light text-content-secondary hover:bg-surface-secondary ${className ?? ''}`}
      title={t('bim.offline_save_hint', {
        defaultValue: 'Download this model to this device so it opens with no network on site.',
      })}
    >
      <Download size={15} />
      {t('bim.offline_save', { defaultValue: 'Save for offline' })}
      {sizeLabel && <span className="text-content-quaternary">({sizeLabel})</span>}
    </button>
  );
}
