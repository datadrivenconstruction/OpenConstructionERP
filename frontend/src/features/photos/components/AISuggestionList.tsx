// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// AI reads a photo and proposes; nothing lands on the record until a person accepts it.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Loader2, Sparkles, X } from 'lucide-react';
import { ConfidenceBadge } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  acceptSuggestion,
  analyzePhoto,
  fetchSuggestions,
  photosKeys,
  rejectSuggestion,
  type AIKind,
  type Suggestion,
} from '../api';
import { editedPayload, suggestionText } from '../model';

const KINDS: AIKind[] = ['caption', 'tags', 'progress', 'hazard'];

function SuggestionRow({ s, photoId }: { s: Suggestion; photoId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((st) => st.addToast);
  const original = suggestionText(s.kind, s.payload);
  const [text, setText] = useState(original);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: photosKeys.suggestions(photoId) });
    qc.invalidateQueries({ queryKey: photosKeys.all });
  };
  const accept = useMutation({
    mutationFn: () => {
      const payload = text === original ? undefined : editedPayload(s.kind, s.payload, text) ?? undefined;
      return acceptSuggestion(s.id, payload);
    },
    onSuccess: refresh,
    onError: (err) => addToast({ type: 'error', title: t('photoArchive.ai.accept_failed'), message: getErrorMessage(err) }),
  });
  const reject = useMutation({
    mutationFn: () => rejectSuggestion(s.id),
    onSuccess: refresh,
    onError: (err) => addToast({ type: 'error', title: t('photoArchive.ai.reject_failed'), message: getErrorMessage(err) }),
  });
  const pending = s.status === 'pending';
  const invalid = text !== original && editedPayload(s.kind, s.payload, text) === null;

  return (
    <li className="space-y-1 rounded-md border border-border-light p-2" data-testid={`suggestion-${s.kind}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium">{t(`photoArchive.ai.kind_${s.kind}`)}</span>
        <ConfidenceBadge score={s.confidence} showScore />
      </div>
      {pending ? (
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-label={t(`photoArchive.ai.kind_${s.kind}`)}
          aria-invalid={invalid}
          className="w-full rounded border border-border-light bg-surface-primary px-2 py-1 text-xs"
        />
      ) : (
        <p className="text-xs text-content-secondary">{original}</p>
      )}
      {pending ? (
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => accept.mutate()}
            disabled={accept.isPending || invalid}
            className="inline-flex items-center gap-1 rounded bg-emerald-600 px-2 py-1 text-xs text-white disabled:opacity-50"
          >
            <Check className="h-3 w-3" aria-hidden />
            {t('photoArchive.ai.accept')}
          </button>
          <button
            type="button"
            onClick={() => reject.mutate()}
            disabled={reject.isPending}
            className="inline-flex items-center gap-1 rounded border border-border-light px-2 py-1 text-xs disabled:opacity-50"
          >
            <X className="h-3 w-3" aria-hidden />
            {t('photoArchive.ai.reject')}
          </button>
        </div>
      ) : (
        <span className="text-2xs uppercase text-content-tertiary">{t(`photoArchive.ai.status_${s.status}`)}</span>
      )}
    </li>
  );
}

export function AISuggestionList({ photoId, canRun = true }: { photoId: string; canRun?: boolean }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [kinds, setKinds] = useState<AIKind[]>(['caption', 'tags']);
  const [waiting, setWaiting] = useState(false);
  const list = useQuery({
    queryKey: photosKeys.suggestions(photoId),
    queryFn: () => fetchSuggestions(photoId),
    refetchInterval: waiting ? 3000 : false,
  });
  const run = useMutation({
    mutationFn: () => analyzePhoto(photoId, kinds),
    onSuccess: () => {
      setWaiting(true);
      setTimeout(() => setWaiting(false), 60_000);
      addToast({ type: 'info', title: t('photoArchive.ai.started') });
    },
    onError: (err) => addToast({ type: 'error', title: t('photoArchive.ai.run_failed'), message: getErrorMessage(err) }),
  });
  const items = list.data ?? [];

  return (
    <div className="space-y-2" data-testid="ai-suggestions">
      <p className="text-2xs text-content-tertiary">{t('photoArchive.ai.notice')}</p>
      {canRun && (
        <div className="flex flex-wrap items-center gap-2">
          {KINDS.map((k) => (
            <label key={k} className="inline-flex items-center gap-1 text-xs">
              <input
                type="checkbox"
                checked={kinds.includes(k)}
                onChange={() => setKinds((cur) => (cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k]))}
              />
              {t(`photoArchive.ai.kind_${k}`)}
            </label>
          ))}
          <button
            type="button"
            onClick={() => run.mutate()}
            disabled={run.isPending || kinds.length === 0}
            className="inline-flex items-center gap-1 rounded bg-oe-blue px-2 py-1 text-xs text-white disabled:opacity-50"
          >
            {run.isPending || waiting ? (
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
            ) : (
              <Sparkles className="h-3 w-3" aria-hidden />
            )}
            {t('photoArchive.ai.run')}
          </button>
        </div>
      )}
      {items.length === 0 ? (
        <p className="text-xs text-content-tertiary">{t('photoArchive.ai.none')}</p>
      ) : (
        <ul className="space-y-2">
          {items.map((s) => (
            <SuggestionRow key={s.id} s={s} photoId={photoId} />
          ))}
        </ul>
      )}
    </div>
  );
}
