// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The visible key to the small language tags on dashboard tiles.
 *
 * A tile whose text is not in the UI language carries a tag ("EN"). The tag's
 * tooltip says why, but a tooltip never shows on a phone and is easy to miss
 * with a mouse, so the card prints the reason once, next to its heading, as a
 * legend: the tags in use followed by "Not yet available in your language".
 * Nothing renders when every tile is in the reader's language.
 */

import clsx from 'clsx';
import { Languages } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { distinctTags } from './contentLanguage';

export function ContentLanguageNote({
  tags,
  className,
  testId = 'content-language-note',
}: {
  /** One entry per tile: its tag, or null when it is in the UI language. */
  tags: readonly (string | null)[];
  className?: string;
  testId?: string;
}) {
  const { t } = useTranslation();
  const shown = distinctTags(tags);
  if (shown.length === 0) return null;
  return (
    <p
      data-testid={testId}
      className={clsx('inline-flex flex-wrap items-center gap-1 text-2xs text-content-tertiary', className)}
    >
      <Languages size={11} aria-hidden="true" />
      {shown.map((tag) => (
        <span key={tag} className="rounded border border-border-light px-1 font-semibold uppercase">
          {tag}
        </span>
      ))}
      <span>{t('dashboard.content_language_fallback', { defaultValue: 'Not yet available in your language' })}</span>
    </p>
  );
}
