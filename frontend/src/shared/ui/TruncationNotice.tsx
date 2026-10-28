// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';

import { isTruncated, type Page } from '@/shared/lib/api';

export interface TruncationNoticeProps {
  /** The page as it came back from the API. */
  page: Pick<Page<unknown>, 'items' | 'total'>;
  className?: string;
}

/**
 * States how much of a collection is on screen when some of it is not.
 *
 * Renders nothing when the page is complete, so a call site can mount it
 * unconditionally. That is deliberate: the alternative is each surface
 * writing its own `total > items.length` test, and a surface that forgets
 * the test looks exactly like one that does not need it.
 *
 * This is the honest half of the paging contract. A list that pages needs
 * page controls; a list that cannot page — a picker, a modal, a dropdown —
 * still has to admit that it is showing a slice.
 *
 * The sentence names no noun on purpose. An earlier draft interpolated one
 * ("Showing 50 of 120 activities"), which reads well in English and forces
 * every other language to agree with a word it is handed at runtime, in
 * whatever gender, number and case that language needs. `cases.showing_count`
 * is the wording already settled and translated in all 40 locales for the
 * same question, so this reuses it rather than minting a key that would ship
 * its English default everywhere until 40 files caught up. The `cases.`
 * prefix is where the string was first needed, not a claim about who owns it.
 */
export function TruncationNotice({ page, className }: TruncationNoticeProps) {
  const { t } = useTranslation();

  if (!isTruncated(page)) return null;

  return (
    <p
      className={clsx('text-xs text-content-tertiary', className)}
      role="status"
      data-testid="truncation-notice"
    >
      {t('cases.showing_count', {
        defaultValue: 'Showing {{shown}} of {{total}}',
        shown: page.items.length,
        total: page.total,
      })}
    </p>
  );
}
