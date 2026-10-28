// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Saved and recent searches for Find Records. Purely presentational: the page
// owns the state - recent from localStorage, saved from the server - and passes
// it down, so this component just renders history and reports intent through
// callbacks. It renders nothing when there is no history and nothing to save,
// staying out of the way for a first-time user.

import { useTranslation } from 'react-i18next';
import { Bookmark, BookmarkCheck, Clock, RotateCcw, Search, Trash2 } from 'lucide-react';
import { Card } from '@/shared/ui';
import { querySignature, type SavedSearch } from './savedSearches';
import type { RetrievalQuery } from './types';

interface SavedSearchesProps {
  recent: RetrievalQuery[];
  saved: SavedSearch[];
  /** Whether the current committed query is worth saving (has any facet). */
  currentCanSave: boolean;
  /** Whether the current committed query is already in the saved list. */
  currentIsSaved: boolean;
  /** A save is in flight; the button waits rather than claiming success early. */
  saveBusy?: boolean;
  /** Short human label for a query, used for recent chips and saved fallback. */
  describeQuery: (q: RetrievalQuery) => string;
  onRun: (q: RetrievalQuery) => void;
  /** Replaying a pin carries the whole row so the page can record the use. */
  onRunSaved: (saved: SavedSearch) => void;
  onSaveCurrent: () => void;
  onRemoveSaved: (id: string) => void;
  onClearRecent: () => void;
}

export function SavedSearches({
  recent,
  saved,
  currentCanSave,
  currentIsSaved,
  saveBusy = false,
  describeQuery,
  onRun,
  onRunSaved,
  onSaveCurrent,
  onRemoveSaved,
  onClearRecent,
}: SavedSearchesProps) {
  const { t } = useTranslation();
  const hasRecent = recent.length > 0;
  const hasSaved = saved.length > 0;

  // Nothing to show and nothing to save: stay out of the way entirely.
  if (!hasRecent && !hasSaved && !currentCanSave) return null;

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-content-primary">
          {t('retrieval.searches_title', { defaultValue: 'Saved and recent searches' })}
        </h2>
        {currentCanSave && (
          <button
            type="button"
            onClick={onSaveCurrent}
            disabled={currentIsSaved || saveBusy}
            className="inline-flex items-center gap-1.5 rounded-md border border-border-light px-2.5 py-1 text-xs font-medium text-content-secondary transition-colors hover:bg-surface-secondary disabled:cursor-default disabled:opacity-50"
          >
            {currentIsSaved ? (
              <BookmarkCheck className="h-3.5 w-3.5" />
            ) : (
              <Bookmark className="h-3.5 w-3.5" />
            )}
            {currentIsSaved
              ? t('retrieval.saved_done', { defaultValue: 'Saved' })
              : t('retrieval.save_current', { defaultValue: 'Save this search' })}
          </button>
        )}
      </div>

      {hasSaved && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-xs font-medium text-content-tertiary">
            <Bookmark className="h-3.5 w-3.5" />
            {t('retrieval.saved_label', { defaultValue: 'Saved' })}
          </div>
          <ul className="space-y-1">
            {saved.map((s) => (
              <li key={s.id} className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => onRunSaved(s)}
                  className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1 text-start text-sm text-content-secondary transition-colors hover:bg-surface-secondary hover:text-content-primary"
                >
                  <Search className="h-3.5 w-3.5 shrink-0 text-content-tertiary" />
                  <span className="truncate">{s.label || describeQuery(s.query)}</span>
                </button>
                <button
                  type="button"
                  onClick={() => onRemoveSaved(s.id)}
                  aria-label={t('retrieval.remove_saved', { defaultValue: 'Remove saved search' })}
                  title={t('retrieval.remove_saved', { defaultValue: 'Remove saved search' })}
                  className="shrink-0 rounded-md p-1 text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-semantic-error"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {hasRecent && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5 text-xs font-medium text-content-tertiary">
              <Clock className="h-3.5 w-3.5" />
              {t('retrieval.recent_label', { defaultValue: 'Recent' })}
            </div>
            <button
              type="button"
              onClick={onClearRecent}
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-content-secondary"
            >
              <RotateCcw className="h-3 w-3" />
              {t('retrieval.clear_recent', { defaultValue: 'Clear' })}
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {recent.map((q) => (
              <button
                key={querySignature(q)}
                type="button"
                onClick={() => onRun(q)}
                className="inline-flex max-w-[16rem] items-center gap-1.5 rounded-full border border-border-light bg-surface-primary px-2.5 py-1 text-xs text-content-secondary transition-colors hover:border-oe-blue/40 hover:text-content-primary"
              >
                <Search className="h-3 w-3 shrink-0 text-content-tertiary" />
                <span className="truncate">{describeQuery(q)}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

export default SavedSearches;
