// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The one switch for semantic search. It is off by default: the language model
// behind it needs about a gigabyte of free memory, and on a machine without
// that headroom loading it is what took the whole app down. So nothing loads
// until someone turns it on here, and the card says what that costs before the
// switch is flipped, using the free memory the server measures right now.
//
// Turning it on also fetches the model when it is not downloaded yet, so there
// is no second "download" switch to find. Turning it off stops new loads at
// once; memory a loaded model already holds comes back on the next restart,
// and the card says so rather than pretending otherwise.

import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { AlertTriangle, CheckCircle2, Loader2, Sparkles } from 'lucide-react';

import { aiEstimatorApi, type EmbeddingModelStatus } from '@/features/ai-estimator/api';

const POLL_MS = 3000;

export default function SemanticModelSettings() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);

  const { data: status } = useQuery({
    queryKey: ['embedding-model-status'],
    queryFn: aiEstimatorApi.embeddingModelStatus,
    retry: false,
    refetchInterval: (query) => (query.state.data?.state === 'downloading' ? POLL_MS : false),
  });

  const enabled = status?.semantic_enabled === true;
  const locked = status?.semantic_locked === true;
  const libraryMissing = status?.state === 'library_missing';

  const handleToggle = useCallback(() => {
    setSaving(true);
    setSaveFailed(false);
    aiEstimatorApi
      .setSemanticSearchEnabled(!enabled)
      .then((next: EmbeddingModelStatus) => {
        qc.setQueryData(['embedding-model-status'], next);
      })
      .catch(() => setSaveFailed(true))
      .finally(() => {
        setSaving(false);
        void qc.invalidateQueries({ queryKey: ['embedding-model-status'] });
      });
  }, [enabled, qc]);

  const required = status?.required_memory_mb ?? 1024;
  const available = status?.available_memory_mb;

  return (
    <div className="rounded-2xl bg-surface-elevated shadow-sm shadow-black/[0.04] p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text">
            <Sparkles size={20} />
          </div>
          <div>
            <h3 className="text-base font-bold text-content-primary">
              {t('settings.semantic_title', { defaultValue: 'Semantic search' })}
            </h3>
            <p className="mt-0.5 text-xs text-content-secondary">
              {t('settings.semantic_desc', {
                defaultValue:
                  'Finds cost items, positions and documents by meaning, not only by exact words. Off by default to keep the app fast and light.',
              })}
            </p>
            <p className="mt-1 text-xs text-content-tertiary">
              {typeof available === 'number'
                ? t('settings.semantic_memory', {
                    defaultValue:
                      'Needs about {{required}} MB of free memory when on. Available now: {{available}} MB.',
                    required,
                    available,
                  })
                : t('settings.semantic_memory_unknown', {
                    defaultValue: 'Needs about {{required}} MB of free memory when on.',
                    required,
                  })}
            </p>
          </div>
        </div>

        {!libraryMissing && !locked && (
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            aria-label={t('settings.semantic_title', { defaultValue: 'Semantic search' })}
            disabled={saving || !status}
            onClick={handleToggle}
            className={clsx(
              'relative inline-flex h-[26px] w-[48px] shrink-0 cursor-pointer rounded-full p-[3px] transition-all duration-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/50 disabled:cursor-wait disabled:opacity-60',
              enabled ? 'bg-oe-blue' : 'bg-gray-200 dark:bg-gray-700',
            )}
          >
            <span
              className={clsx(
                'pointer-events-none h-5 w-5 rounded-full bg-white shadow-lg transition-transform duration-300',
                enabled ? 'translate-x-[22px] rtl:-translate-x-[22px]' : 'translate-x-0',
              )}
            />
          </button>
        )}
      </div>

      <div className="mt-3 space-y-2 text-xs" role="status">
        {libraryMissing && (
          <p className="text-content-tertiary">
            {t('onboarding.semantic_model_library_missing', {
              defaultValue:
                'Semantic search is not part of this installation. Everything else works without it.',
            })}
          </p>
        )}
        {!libraryMissing && locked && (
          <p className="text-content-tertiary">
            {enabled
              ? t('settings.semantic_locked_on', {
                  defaultValue: 'Switched on for this installation by its administrator.',
                })
              : t('settings.semantic_locked_off', {
                  defaultValue: 'Switched off for this installation by its administrator.',
                })}
          </p>
        )}
        {!enabled && !libraryMissing && status?.memory_low && (
          <p className="flex items-start gap-1.5 text-semantic-warning">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            {t('settings.semantic_memory_low', {
              defaultValue:
                'This computer has less free memory than semantic search needs. If you turn it on, the model may not load or the app may slow down.',
            })}
          </p>
        )}
        {enabled && status?.state === 'downloading' && (
          <p className="flex items-center gap-1.5 text-content-secondary">
            <Loader2 size={14} className="animate-spin text-oe-blue" />
            {t('settings.semantic_downloading', {
              defaultValue: 'Downloading the model: {{done}} of {{total}} files',
              done: status.files_done,
              total: status.files_total,
            })}
          </p>
        )}
        {enabled && status?.state === 'ready' && (
          <p className="flex items-center gap-1.5 text-semantic-success">
            <CheckCircle2 size={14} />
            {status.embedder && (status.embedder as { state?: string }).state === 'ready'
              ? t('settings.semantic_ready', { defaultValue: 'On and ready' })
              : t('settings.semantic_on_pending', {
                  defaultValue: 'On. The model loads with the first search.',
                })}
          </p>
        )}
        {enabled && status?.state === 'failed' && (
          <p className="flex items-start gap-1.5 text-semantic-warning">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            {t('onboarding.semantic_model_failed', {
              defaultValue: 'The model could not be downloaded. Everything else keeps working.',
            })}
          </p>
        )}
        {enabled && !locked && (
          <p className="text-content-tertiary">
            {t('settings.semantic_restart_note', {
              defaultValue:
                'Turning it off stops new loads at once. Memory already in use is released after the app restarts.',
            })}
          </p>
        )}
        {saveFailed && (
          <p className="text-semantic-error">
            {t('settings.semantic_save_error', {
              defaultValue:
                'Could not change the setting. Only an administrator can turn semantic search on or off.',
            })}
          </p>
        )}
      </div>
    </div>
  );
}
