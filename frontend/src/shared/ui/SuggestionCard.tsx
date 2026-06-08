/**
 * <SuggestionCard> — one shared shape for an AI suggestion the user
 * reviews before anything happens.
 *
 * The platform rule is "AI proposes, human confirms": this card never
 * applies itself. It shows what the AI suggests, how sure it is, and a
 * plain-language reason, then leaves Accept / Edit / Reject to the user.
 * Pass the action callbacks to make it interactive; omit them for a
 * read-only review surface.
 *
 * `title` and `reason` arrive pre-translated (callers usually resolve
 * per-module `<feature>.*` keys); only the generic chrome (the action
 * labels, "why", "learn more") is translated here.
 */

import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Check, Pencil, X } from 'lucide-react';
import { Button } from './Button';
import { ConfidenceBadge, type ConfidenceLevel } from './ConfidenceBadge';

export interface SuggestionCardProps {
  /** Small leading icon (e.g. a lucide glyph for the suggestion kind). */
  icon?: ReactNode;
  /** Pre-translated headline of the suggestion. */
  title: string;
  /** Pre-translated plain-language "why" (kept short). */
  reason?: ReactNode;
  /** Backend-owned band, shown via the shared ConfidenceBadge. */
  confidence?: ConfidenceLevel | string;
  /** Raw 0..1 score, used only when `confidence` is absent. */
  score?: number;
  onAccept?: () => void;
  onEdit?: () => void;
  onReject?: () => void;
  /** Optional "learn more" affordance (opens the reasoning / source). */
  onLearnMore?: () => void;
  /** Disable the action buttons while a mutation is in flight. */
  busy?: boolean;
  className?: string;
}

export function SuggestionCard({
  icon,
  title,
  reason,
  confidence,
  score,
  onAccept,
  onEdit,
  onReject,
  onLearnMore,
  busy = false,
  className,
}: SuggestionCardProps) {
  const { t } = useTranslation();
  const hasActions = Boolean(onAccept || onEdit || onReject);

  return (
    <div
      className={clsx(
        'rounded-md border border-border-light bg-surface-primary p-3 text-left',
        className,
      )}
    >
      <div className="flex items-start gap-2">
        {icon && <span className="mt-0.5 shrink-0 text-content-tertiary">{icon}</span>}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-content-primary">{title}</p>
          {reason && (
            <p className="mt-0.5 text-xs leading-relaxed text-content-secondary">{reason}</p>
          )}
        </div>
        {(confidence !== undefined || typeof score === 'number') && (
          <ConfidenceBadge level={confidence} score={score} className="shrink-0" />
        )}
      </div>

      {(hasActions || onLearnMore) && (
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          {onAccept && (
            <Button
              variant="primary"
              size="sm"
              icon={<Check size={13} />}
              disabled={busy}
              onClick={onAccept}
            >
              {t('suggestion.accept', { defaultValue: 'Accept' })}
            </Button>
          )}
          {onEdit && (
            <Button
              variant="secondary"
              size="sm"
              icon={<Pencil size={13} />}
              disabled={busy}
              onClick={onEdit}
            >
              {t('suggestion.edit', { defaultValue: 'Edit' })}
            </Button>
          )}
          {onReject && (
            <Button
              variant="ghost"
              size="sm"
              icon={<X size={13} />}
              disabled={busy}
              onClick={onReject}
            >
              {t('suggestion.reject', { defaultValue: 'Reject' })}
            </Button>
          )}
          {onLearnMore && (
            <button
              type="button"
              onClick={onLearnMore}
              className="ml-auto text-xs font-medium text-oe-blue-text hover:underline"
            >
              {t('suggestion.learn_more', { defaultValue: 'Learn more' })}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
