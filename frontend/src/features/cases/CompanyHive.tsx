// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// CompanyHive - the kinds of company a case is written for, as a honeycomb.
//
// The case page already draws its modules as a comb (ModuleHive.tsx). This is
// the other half of the same question: a case has a REACH across the product,
// and it has an AUDIENCE. Both are short lists the reader should be able to
// take in at a glance, so both are the same drawing. `Hive` is shared verbatim;
// only the cargo differs, which is why there is no second layout here to drift
// from the first one.
//
// THREE DIFFERENCES FROM THE MODULE COMB, all of them in the data:
//
//   TINT IS PER CELL. A case's modules share the case's discipline colour,
//   because they are that one case's route through the product. Company types
//   are not the case's property - they exist across the whole catalogue and
//   each carries its own colour on the hub's "I work as..." selector. A comb
//   that repainted them in the case's discipline would be inventing a
//   relationship the palette elsewhere denies.
//
//   THE CELLS CARRY PHOTOGRAPHS. There is a company scene on disk for each of
//   these (caseFaces.ts), the same picture the hub's selector uses, so the
//   cell can be the firm rather than a glyph standing in for it. It is washed
//   back behind the glyph and the name: decorative, and out of the accessible
//   tree, because the label is what a reader has to be able to act on.
//
//   THE CELLS ARE BIGGER. Four company names are a smaller band than a dozen
//   module names, and at module size a band of three read as an unfinished
//   comb rather than a small complete one. The count problem is answered by
//   the size of the cells, not by padding the comb out with cells for company
//   types the case was not written for - a hexagon nobody can act on reads as
//   disabled, and five of those beside three live ones is a worse answer than
//   three alone. The denominator is a fact and it is in the caption, in words.

import type { ReactElement } from 'react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Hive, type HiveCell } from './ModuleHive';
import { COMPANY_TYPE_BY_ID, COMPANY_TYPE_META } from './companyTypes';
import { companyThumbFor } from './caseFaces';
import { useCasesStore } from './useCasesStore';
import type { CompanyType, Playbook } from './types';

export interface CaseCompanyHiveProps {
  playbook: Playbook;
  /**
   * How the comb is being asked to sit.
   *
   * `band` is the original: a box that hugs its own content across the page,
   * caption beside the cells because there is room for it there.
   *
   * `aside` is the narrow column beside the process strip. Three things have
   * to change together for that, and changing any one of them alone looks
   * broken. The caption goes ABOVE the cells, because 144px of the column
   * spent on a caption is width the comb needs. The cells come down from 136
   * to 96, so the widest comb in the catalogue still fits the column without
   * a scroller of its own (the arithmetic is at `cellWidth` below). And the
   * box takes the column's width rather than hugging its content, so the two
   * columns are one height instead of two ragged ones.
   */
  variant?: 'band' | 'aside';
}

/**
 * The company comb for one case: the kinds of firm this case was written for,
 * each in its own colour, each a way into the rest of the catalogue.
 *
 * Activating a cell narrows the case library to that kind of company and opens
 * it - the same filter the hub's "I work as..." selector sets, written to the
 * same store, so the hub comes up already answering "what else is here for a
 * firm like mine". Renders nothing for a case that names no company type,
 * the same as the module comb does for a case that reaches no module.
 */
export function CaseCompanyHive({
  playbook,
  variant = 'band',
}: CaseCompanyHiveProps): ReactElement | null {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const setCompanyTypes = useCasesStore((s) => s.setCompanyTypes);

  // Unknown ids are dropped rather than drawn: a company type renamed in
  // `types.ts` and left behind in a case file has no label, no colour and no
  // hub filter to lead to, and a cell for it would be all three of those
  // failures at once.
  const cells: HiveCell[] = playbook.companyTypes.flatMap((id: CompanyType) => {
    const meta = COMPANY_TYPE_BY_ID[id];
    if (!meta) return [];
    const label = t(meta.labelKey, { defaultValue: meta.labelDefault });
    return [
      {
        id: meta.id,
        label,
        icon: meta.icon,
        tint: meta.tint,
        image: companyThumbFor(meta.id) ?? undefined,
        // The drawing says the name, the accessible name says what happens.
        // Read out as bare nouns these cells are indistinguishable from a
        // caption, and a reader who cannot see the hexagon has no other way to
        // learn that the row is a way somewhere. Printed instead of the name,
        // the same phrase would turn a compact band into a column of
        // sentences. The key predates the comb: this row was chips before it
        // was cells, it said this then, and the redesign is what dropped it.
        actionLabel: t('cases.card.company_filter', {
          defaultValue: 'Show cases for {{company}}',
          company: label,
        }),
      },
    ];
  });
  if (cells.length === 0) return null;

  const heading = t('cases.company_hive.title', {
    defaultValue: 'Written for these kinds of company',
  });

  // Same rule the module comb uses: a band deep enough to stay compact once
  // there are more than six cells, a single zigzag strip below that.
  const rows = cells.length > 6 ? 2 : 1;
  const aside = variant === 'aside';
  // Measured, not chosen. `hiveBand` advances a column every 3/4 of a cell, so
  // the widest comb this catalogue holds - four company types, which 16 cases
  // have and none exceeds - is 3 * 0.75 * cellWidth + cellWidth wide. The
  // column it has to fit inside is `lg:w-96` minus `p-4` on both sides, and
  // `w-96` is 360px here rather than the nominal 384: this app's root font is
  // 15px, so every rem-based Tailwind width is 15/16 of the number in its
  // name. That leaves 328px, and 96 is the cell that fits four of them into
  // it (312) while staying at or above the 96 where `Hive` switches the name
  // back up to `text-xs`. At 136 the same comb is 442px and would sit in a
  // horizontal scroller inside a page that already has one.
  //
  // One number per render, not per breakpoint: the band is laid out in baked
  // pixels, so a cell cannot be 136 on a phone and 96 in the column without
  // drawing the whole comb twice. The aside takes the smaller cell wherever it
  // is used, which is the case page, where it is a column from `lg` up and the
  // block under the strip below that.
  const cellWidth = aside ? 96 : 136;

  return (
    <section
      aria-label={heading}
      className={clsx(
        'w-fit max-w-full rounded-xl border border-border-light bg-surface-primary p-4',
        // The column keeps hugging its comb rather than taking a fixed width,
        // because three company types is what 153 of the 198 cases carry and a
        // box sized for the widest of them would stand mostly empty on all of
        // those. It only refuses to be SHRUNK (`lg:shrink-0`), and it is
        // capped so that a locale whose caption is a long line cannot widen
        // the column at the strip's expense - past the cap the caption wraps.
        aside && 'lg:max-w-96 lg:shrink-0',
      )}
    >
      <div
        className={clsx(
          'flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-5',
          // Caption back over the cells once this is a column, and the row
          // rules undone with it: `sm:items-center` on a column would centre
          // the caption over a comb it should be left-aligned with.
          //
          // `lg:h-full` plus `lg:justify-center` because the box is a flex
          // item that stretches to the row's height, and the row is now as
          // tall as the process column's strip plus the market pack beneath
          // it. Without these the comb sits at the top of a box with 70px of
          // nothing under it; with them the group is centred in the space the
          // neighbour decides. It centres the caption WITH the comb rather
          // than over it, which is why `items-stretch` above stays.
          aside && 'lg:h-full lg:flex-col lg:items-stretch lg:justify-center lg:gap-3',
        )}
      >
        <div className={clsx('min-w-0 sm:w-36 sm:shrink-0', aside && 'lg:w-auto lg:shrink')}>
          <p className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
            {heading}
          </p>
          {/* The denominator is real here, unlike the module comb's: the
              company types are a closed union in `types.ts`, so "3 of 8" is a
              fact about the catalogue rather than a number somebody chose.

              `count` is bound to the TOTAL and the subset rides in `shown`,
              which reads backwards until you know why. i18next picks the
              plural form from `count`, and in "3 of 8 company types" the noun
              is governed by the eight, not the three: the languages that
              inflect it want the form the TOTAL asks for. Bound to the subset,
              every one of them would agree with the wrong number while the
              English output went on looking perfectly correct. */}
          <p className="text-xs text-content-tertiary">
            {t('cases.company_hive.count', {
              defaultValue: '{{shown}} of {{count}} company types',
              defaultValue_other: '{{shown}} of {{count}} company types',
              shown: cells.length,
              count: COMPANY_TYPE_META.length,
            })}
          </p>
        </div>
        <Hive
          cells={cells}
          label={heading}
          onSelect={(id) => {
            setCompanyTypes([id as CompanyType]);
            navigate('/cases');
          }}
          cellWidth={cellWidth}
          rows={rows}
        />
      </div>
    </section>
  );
}
