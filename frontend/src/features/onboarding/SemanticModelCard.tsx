// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The semantic-search encoder, offered in the setup wizard as what it is: an
// optional extra that downloads in the background and that nothing waits for.
//
// The card exists because the download is invisible otherwise. It never starts
// on its own, desktop included (no network fetch without an explicit user
// action), so the card is also the consent: it states size and purpose before
// the switch is flipped. Once asked for it takes minutes, and until it finishes
// semantic search
// declines out loud with a 503 while lexical search keeps answering. A user who
// cannot see that state reads the decline as a broken product.
//
// Five states, because the reader's next move differs in each one: install the
// extra, wait, retry, use it, or turn it on. The toggle is only meaningful in
// the last of them - once weights are on their way or already here there is
// nothing left to decide, so the card shows progress instead of a control that
// would do nothing.
//
// Nothing here can hold the wizard up. The status query is a plain poll with no
// blocking states, the toggle only records an intention, and the request that
// acts on it is fired without being awaited.
//
// Note for anyone translating or shortening these strings. The reassurance
// clauses are load-bearing, not padding: "Search works without it" on the
// header, "Everything else works without it" on library_missing, and the
// equivalent on the failed state. They are the only place in the wizard that
// tells a user this download is optional. Drop them and the failure states read
// as a broken install, which is the reaction the card was built to prevent, and
// users retry a download that was never required. Keep the clause even where a
// language needs more words for it than English does.
//
// Two variables, {{done}} and {{total}}, must both survive and must stay
// reorderable - languages put the count and the total in the opposite order.

import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { Check, CheckCircle2, Loader2, AlertTriangle, Sparkles } from 'lucide-react';

import { aiEstimatorApi, type EmbeddingModelStatus } from '@/features/ai-estimator/api';

/** How often to re-ask while weights are arriving. */
const POLL_MS = 3000;

export interface SemanticModelCardProps {
  /** Whether the user wants the encoder. Owned by the wizard step. */
  enabled: boolean;
  onToggle: (next: boolean) => void;
  /** Injected by the tests; defaults to the real endpoint. */
  fetchStatus?: () => Promise<EmbeddingModelStatus>;
  onRetry?: () => void;
}

export function SemanticModelCard({
  enabled,
  onToggle,
  fetchStatus,
  onRetry,
}: SemanticModelCardProps) {
  const { t } = useTranslation();

  const { data: status } = useQuery({
    queryKey: ['embedding-model-status'],
    queryFn: fetchStatus ?? aiEstimatorApi.embeddingModelStatus,
    // A deployment without the endpoint (an older backend) must not turn this
    // into a retry storm, and it must not surface an error either: the card
    // simply renders its unknown state and the wizard moves on.
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.state === 'downloading' ? POLL_MS : false,
  });

  const state = status?.state;

  const handleRetry = useCallback(() => {
    // Deliberately not awaited: the server answers as soon as the transfer is
    // scheduled, and the poll above picks the new state up.
    void aiEstimatorApi.installEmbeddingModel().catch(() => undefined);
    onRetry?.();
  }, [onRetry]);

  return (
    <div className="rounded-2xl bg-surface-elevated shadow-sm shadow-black/[0.04] p-6">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text">
            <Sparkles size={20} />
          </div>
          <div>
            <h3 className="text-base font-bold text-content-primary">
              {t('onboarding.semantic_model_title', {
                defaultValue: 'Semantic search model',
              })}
            </h3>
            <p className="text-xs text-content-tertiary">
              {t('onboarding.semantic_model_optional', {
                defaultValue:
                  'Optional - downloads in the background. Search works without it.',
              })}
            </p>
            {state !== 'ready' && state !== 'library_missing' && !status?.locked && (
              <p className="mt-1 text-xs text-content-tertiary">
                {t('onboarding.semantic_model_consent', {
                  defaultValue:
                    'About 470 MB, downloaded only when you switch this on. It lets search find cost items by meaning, not only by exact words.',
                })}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          {state === 'ready' ? (
            <div className="flex items-center gap-2 text-sm text-semantic-success">
              <CheckCircle2 size={16} />
              <span className="font-medium">
                {t('onboarding.semantic_model_ready', { defaultValue: 'Installed' })}
              </span>
            </div>
          ) : state === 'downloading' ? (
            <div className="flex items-center gap-2 text-sm text-content-secondary">
              <Loader2 size={14} className="animate-spin text-oe-blue" />
              <span>
                {t('onboarding.semantic_model_downloading', {
                  defaultValue: 'Downloading {{done}} of {{total}} files',
                  done: status?.files_done ?? 0,
                  total: status?.files_total ?? 0,
                })}
              </span>
            </div>
          ) : state === 'library_missing' || status?.locked ? (
            <span className="text-sm text-content-tertiary">
              {t('onboarding.semantic_model_unavailable', {
                defaultValue: 'Not available here',
              })}
            </span>
          ) : (
            <SwitchControl enabled={enabled} onToggle={() => onToggle(!enabled)} />
          )}
        </div>
      </div>

      {state === 'downloading' && (
        <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary">
          <div
            className="h-full rounded-full bg-oe-blue transition-all duration-500"
            style={{ width: `${status?.percent ?? 0}%` }}
            role="progressbar"
            aria-valuenow={status?.percent ?? 0}
            aria-valuemin={0}
            aria-valuemax={100}
          />
        </div>
      )}

      {state === 'library_missing' && (
        <p className="mt-3 text-xs text-content-tertiary" role="status">
          {t('onboarding.semantic_model_library_missing', {
            defaultValue:
              'Semantic search is not part of this installation. Everything else works without it.',
          })}
        </p>
      )}

      {/* An operator has switched this off for the whole deployment, so the
          toggle above is gone rather than dead. Saying why beats a control
          that accepts a click and does nothing. */}
      {state !== 'library_missing' && status?.locked && (
        <p className="mt-3 text-xs text-content-tertiary" role="status">
          {t('onboarding.semantic_model_locked', {
            defaultValue:
              'Turned off for this installation by its administrator. Everything else works without it.',
          })}
        </p>
      )}

      {state === 'failed' && (
        <div className="mt-3 flex items-start gap-2" role="status">
          <AlertTriangle size={14} className="mt-0.5 shrink-0 text-semantic-warning" />
          <div className="text-xs text-content-secondary">
            <p>
              {t('onboarding.semantic_model_failed', {
                defaultValue:
                  'The model could not be downloaded. Everything else keeps working.',
              })}
            </p>
            <button
              type="button"
              onClick={handleRetry}
              className="mt-1 font-medium text-oe-blue hover:underline"
            >
              {t('onboarding.semantic_model_retry', { defaultValue: 'Try again' })}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * The wizard's switch, restated here rather than imported.
 *
 * The original lives inside OnboardingWizard.tsx, which imports this card, so
 * reaching for it would close an import cycle. Promoting it to shared/ui is the
 * right fix and is a change to every one of its call sites, not a detail of
 * this card.
 */
function SwitchControl({ enabled, onToggle }: { enabled: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      onClick={onToggle}
      className={clsx(
        'group relative inline-flex h-[26px] w-[48px] shrink-0 cursor-pointer rounded-full p-[3px] transition-all duration-300 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/50',
        enabled
          ? 'bg-gradient-to-r from-oe-blue to-blue-500 shadow-[inset_0_0_0_1px_rgba(255,255,255,0.1)]'
          : 'bg-gray-200 dark:bg-gray-700 shadow-[inset_0_1px_3px_rgba(0,0,0,0.1)]',
      )}
    >
      <span
        className={clsx(
          'pointer-events-none flex h-5 w-5 items-center justify-center rounded-full bg-white shadow-lg ring-0 transition-all duration-300 ease-in-out',
          enabled ? 'translate-x-[22px] scale-[1.05]' : 'translate-x-0 scale-100',
        )}
      >
        {enabled && <Check size={11} className="text-oe-blue" strokeWidth={3} />}
      </span>
    </button>
  );
}
