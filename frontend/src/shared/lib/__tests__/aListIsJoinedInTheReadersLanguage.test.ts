// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// `moduleNames.join(', ')` writes one language's separator for every reader.
// The case card assembled two localized sentences that way: the keys went out
// to forty two languages and the comma between the items inside them stayed
// Latin, so a Japanese reader got "Projects, BOQ, 4D Schedule" where the
// enumeration mark is U+3001 and an Arabic reader got a Latin comma where the
// Arabic one is.
//
// It was invisible to the gate that exists for exactly this question.
// `numbersAreWrittenInTheAppLanguage` scans for `new Intl.ListFormat()` built
// without a locale, so it can only see a call that was made. Code that never
// calls Intl at all leaves nothing for it to match: a gate written around the
// SHAPE OF A CALL is blind to the path that avoided the call.
//
// This file pins the fix, and one thing about the fix that is easy to get
// wrong in the obvious direction - which is why it is a test and not a
// comment. `Intl.ListFormat` offers a `type: 'unit'`, and for a list of module
// names that name reads like the right pick. It is not: in CLDR that type
// describes a list of MEASUREMENTS, "3 ft 7 in", so Chinese joins it with
// nothing whatsoever. Reaching for it would turn a wrong separator into no
// separator, which is a worse bug wearing the fix's clothes.
//
// Following the house rule from `formatCompactCurrency.test.ts`: the exact
// glyphs and spacing belong to the engine's CLDR data and move between ICU
// versions, so what is asserted here is the property that was broken, not the
// string that happens to come back today.
import i18next from 'i18next';
import { afterAll, describe, expect, it } from 'vitest';

import { fmtList } from '../formatters';
// Imported here rather than awaited inside the last case, and the placement is
// the point. Reaching `@/app/i18n` pulls the module registry and the English
// bundle through the transform, which measured about nine seconds on this
// machine against a fifteen second per-test budget. Inside the case that cost
// counted against the case: it passed with a couple of seconds to spare on an
// idle machine and blew through the budget whenever the machine was busy,
// failing as a timeout that reads like a broken assertion and sends the next
// reader looking for a defect in the formatter. At module scope the same work
// is collection cost, which no per-test timeout bounds, and the case is left
// measuring what it is about.
import { SUPPORTED_LANGUAGES } from '@/app/i18n';

// The app's `languageChanged` listener fetches each language's bundle. Walking all of
// them below then held every locale in one fork and ran it past 4 GB; fmtList needs none.
i18next.off('languageChanged');
void i18next.init({ lng: 'en', resources: {}, initAsync: false });
const original = i18next.language;
afterAll(() => {
  void i18next.changeLanguage(original);
});

const ITEMS = ['Projects', 'BOQ', 'Schedule'];

async function listIn(lang: string, mode?: 'list' | 'prose'): Promise<string> {
  await i18next.changeLanguage(lang);
  return fmtList(ITEMS, mode);
}

describe('fmtList', () => {
  it('leaves English exactly as the hand-written join left it', async () => {
    // The point of saying so out loud: this change is meant to be invisible to
    // the majority of readers. If English moves, the fix is doing something
    // besides fixing the languages that were wrong.
    expect(await listIn('en')).toBe('Projects, BOQ, Schedule');
  });

  it('separates the items in Chinese instead of running them together', async () => {
    const text = await listIn('zh');
    // The assertion that kills `type: 'unit'`. Concatenation is shorter than
    // any separated form, so comparing against the bare join is a check no
    // separator-free output can pass, whatever glyph the engine chooses.
    expect(text.length).toBeGreaterThan(ITEMS.join('').length);
    for (const item of ITEMS) expect(text).toContain(item);
  });

  it('gives CJK readers their own enumeration mark rather than a Latin comma', async () => {
    for (const lang of ['zh', 'ja']) {
      const text = await listIn(lang);
      expect(text).not.toContain(', ');
      expect(text).toContain('、');
    }
  });

  it('gives an Arabic reader a separator from their own script', async () => {
    const text = await listIn('ar');
    expect(text).not.toContain(', ');
    for (const item of ITEMS) expect(text).toContain(item);
  });

  it('never drops an item, in any language the product ships', async () => {
    // The silent failure worth guarding: a list that loses a member reads as a
    // complete list. Checked across every language rather than a sample,
    // because the engine's data differs per locale and a sample is a claim
    // about the ones sampled.
    for (const { code } of SUPPORTED_LANGUAGES) {
      const text = await listIn(code);
      for (const item of ITEMS) {
        expect(text, `${code} dropped ${item}`).toContain(item);
      }
    }
  });

  it('says nothing for an empty list and adds no punctuation to a single item', async () => {
    await i18next.changeLanguage('en');
    expect(fmtList([])).toBe('');
    expect(fmtList(['Projects'])).toBe('Projects');
    // A blank entry is not an item. Left unfiltered it would draw a separator
    // with nothing on one side of it.
    expect(fmtList(['Projects', '  ', 'BOQ'])).toBe('Projects, BOQ');
  });

  it('offers a prose form that differs from the bare list', async () => {
    // Two modes exist because a label takes an enumeration and a sentence
    // takes a conjunction. If they ever collapse to the same output the
    // parameter is dead weight and the call sites are lying about intent.
    await i18next.changeLanguage('en');
    expect(fmtList(ITEMS, 'prose')).not.toBe(fmtList(ITEMS, 'list'));
    expect(fmtList(ITEMS, 'prose')).toContain('and');
  });
});
