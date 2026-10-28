// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What to call a funding deadline on screen.
//
// A derived deadline is written by the server when an award is recorded, and
// its title is stored as a sentence in the language of whoever wrote the
// service. That sentence cannot be translated later, so a German municipality
// reading its own deadline list sees "Records may be destroyed" in the middle
// of a page that is otherwise entirely German. The stored title is therefore
// treated as an internal label, and the screen reads the kind instead, which
// is an enum and is translated in every locale.
//
// A deadline someone typed themselves is different: those are their words,
// not the server's, and translating them would be losing what they wrote.

import type { useTranslation } from 'react-i18next';

import type { FundingDisbursement, FundingObligation } from './api';

type Translate = ReturnType<typeof useTranslation>['t'];

type LabelledObligation = Pick<FundingObligation, 'kind' | 'title' | 'source' | 'due_on'> &
  Partial<Pick<FundingObligation, 'title_key'>>;

/**
 * The name of a deadline in the reader's language.
 *
 * `draws` is optional and only changes the spend-window case: several draws
 * on one award each start their own spend window, and without the reference
 * the list shows two rows with the same name and different dates. They are
 * matched on the deadline the receipt stamped onto the draw, which is the
 * same date the obligation was created with.
 *
 * That match is not a key. Two draws received on the same day under the same
 * terms land on the same deadline, and then no reference is shown at all,
 * because a row labelled with the wrong draw is worse than a row labelled
 * with none: the date is still there to tell them apart, and a confident
 * wrong answer is not.
 */
export function obligationLabel(
  row: LabelledObligation,
  t: Translate,
  draws: FundingDisbursement[] = [],
): string {
  // An empty key is the server saying these are somebody's own words, and it
  // is taken at face value rather than decided again here. Deciding it here
  // from `source` got one case wrong: a condition copied out of an award
  // notice is typed by a person exactly as a manual note is, and the screen
  // replaced what they had written with "Condition of the award".
  if (row.title_key === '' && row.title.trim()) return row.title;
  // A server predating `title_key` sends nothing at all rather than an empty
  // string, and then the old local rule is the only one there is.
  if (row.title_key === undefined && row.source === 'manual' && row.title.trim()) return row.title;

  // The server states the key now, so take it rather than rebuilding it here
  // and leaving two places to disagree about what a kind is called. The
  // fallback is for a server that predates the field; it builds the same key
  // the server would have sent.
  const label = t(row.title_key || `funding.obligation_kind.${row.kind}`, {
    defaultValue: row.title || row.kind,
  });
  if (row.kind !== 'spend_window' || !row.due_on) return label;

  const matches = draws.filter((item) => item.spend_deadline_on === row.due_on);
  const draw = matches.length === 1 ? matches[0] : undefined;
  if (!draw) return label;
  return `${label} · ${draw.code || `#${draw.sequence}`}`;
}
