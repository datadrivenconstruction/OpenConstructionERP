/**
 * <ConfidenceBadge> — one shared way to show how sure the AI is.
 *
 * Replaces the per-module copies (e.g. the local badge in
 * features/boq/AISmartPanel) that each rendered a raw lowercase enum
 * (`high`/`medium`/`low`) straight into the DOM, leaking an
 * untranslated string. This one always renders a translated label.
 *
 * Banding rules (clarity plan, check 5 + Q2):
 *  - When the backend already owns the band (`level`), it is shown
 *    as-is and never re-thresholded.
 *  - When only a raw 0..1 `score` is given, it is thresholded with the
 *    provisional cutoffs below. Those stay provisional until the real
 *    AI-match score distribution is signed off; do not hard-wire them
 *    into business logic elsewhere — import `bandForScore` instead so
 *    there is a single place to change.
 */

import { useTranslation } from 'react-i18next';
import { Badge } from './Badge';

export type ConfidenceLevel = 'high' | 'medium' | 'low';

/** Provisional score cutoffs — see the banding note above. */
export const CONFIDENCE_HIGH_MIN = 0.8;
export const CONFIDENCE_MEDIUM_MIN = 0.5;

export function bandForScore(score: number): ConfidenceLevel {
  if (score >= CONFIDENCE_HIGH_MIN) return 'high';
  if (score >= CONFIDENCE_MEDIUM_MIN) return 'medium';
  return 'low';
}

/** Accepts the platform's confidence words and the cost-certainty colour
 *  bands (green/yellow/red) so a single component covers both. */
function normalizeLevel(level: string): ConfidenceLevel | undefined {
  const l = level.trim().toLowerCase();
  if (l === 'high' || l === 'green') return 'high';
  if (l === 'medium' || l === 'med' || l === 'yellow') return 'medium';
  if (l === 'low' || l === 'red') return 'low';
  return undefined;
}

const LEVEL_VARIANT = {
  high: 'success',
  medium: 'warning',
  low: 'error',
} as const;

const LEVEL_DEFAULT_LABEL: Record<ConfidenceLevel, string> = {
  high: 'High confidence',
  medium: 'Medium confidence',
  low: 'Low confidence',
};

export interface ConfidenceBadgeProps {
  /** Pre-resolved band from the backend. Wins over `score` and is never
   *  re-thresholded. Plain confidence words or green/yellow/red bands. */
  level?: ConfidenceLevel | string;
  /** Raw 0..1 score. Only thresholded into a band when no `level` is given. */
  score?: number;
  /** Append the numeric score (e.g. "82%") after the label. */
  showScore?: boolean;
  size?: 'sm' | 'md';
  className?: string;
}

export function ConfidenceBadge({
  level,
  score,
  showScore = false,
  size = 'sm',
  className,
}: ConfidenceBadgeProps) {
  const { t } = useTranslation();

  const resolved: ConfidenceLevel | undefined =
    level !== undefined
      ? normalizeLevel(String(level))
      : typeof score === 'number'
        ? bandForScore(score)
        : undefined;

  if (!resolved) return null;

  const label = t(`confidence_badge.${resolved}`, {
    defaultValue: LEVEL_DEFAULT_LABEL[resolved],
  });
  const pct = typeof score === 'number' ? Math.round(score * 100) : undefined;

  return (
    <Badge variant={LEVEL_VARIANT[resolved]} size={size} dot className={className}>
      {label}
      {showScore && pct !== undefined && (
        <span className="ml-1 tabular-nums opacity-80">
          {t('confidence_badge.score', { defaultValue: '{{pct}}%', pct })}
        </span>
      )}
    </Badge>
  );
}
