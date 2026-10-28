// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui';

/**
 * ProjectStatusBadge (#274) - renders a project's lifecycle status as a
 * coloured pill with an i18n label.
 *
 * The backend stores status as a free-form string (<=50 chars), but the UI
 * curates a recommended set - active, on_hold, finished, cancelled,
 * archived - each mapped to a Badge variant and a translated label. Any value
 * outside the curated set still renders (humanised + neutral colour) so a
 * custom status set elsewhere never shows a blank or breaks the layout.
 */

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

/** The curated, recommended project statuses, in lifecycle order. */
export const CURATED_PROJECT_STATUSES = [
  'active',
  'on_hold',
  'finished',
  'cancelled',
  'archived',
] as const;

export type CuratedProjectStatus = (typeof CURATED_PROJECT_STATUSES)[number];

const STATUS_VARIANT: Record<CuratedProjectStatus, BadgeVariant> = {
  active: 'success',
  on_hold: 'warning',
  finished: 'neutral',
  // Cancelled is a terminal, abandoned state - red to read as negative,
  // distinct from the neutral "finished" (completed) and "archived" (filed).
  cancelled: 'error',
  archived: 'neutral',
};

const STATUS_LABEL_DEFAULT: Record<CuratedProjectStatus, string> = {
  active: 'Active',
  on_hold: 'On hold',
  finished: 'Finished',
  cancelled: 'Cancelled',
  archived: 'Archived',
};

/** Title-case an unknown status token (e.g. "in_review" -> "In review"). */
function humanise(status: string): string {
  const spaced = status.replace(/[_-]+/g, ' ').trim();
  if (!spaced) return status;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Resolve a status string to its translated label (curated or humanised). */
export function useProjectStatusLabel(): (status: string) => string {
  const { t } = useTranslation();
  return (status: string): string => {
    const key = status as CuratedProjectStatus;
    if (key in STATUS_LABEL_DEFAULT) {
      return t(`projects.status.${key}`, { defaultValue: STATUS_LABEL_DEFAULT[key] });
    }
    return humanise(status);
  };
}

export function ProjectStatusBadge({
  status,
  size = 'sm',
  dot = true,
  className,
}: {
  status: string;
  size?: 'sm' | 'md';
  dot?: boolean;
  className?: string;
}) {
  const label = useProjectStatusLabel()(status);
  const key = status as CuratedProjectStatus;
  const variant: BadgeVariant = key in STATUS_VARIANT ? STATUS_VARIANT[key] : 'neutral';

  return (
    <Badge variant={variant} size={size} dot={dot} className={className}>
      {label}
    </Badge>
  );
}
