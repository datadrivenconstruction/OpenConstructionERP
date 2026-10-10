// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A register is searched by people who do not type the way the record was
 * written: a site engineer on a phone keyboard leaves the diacritics out, a
 * colleague on an English interface types a Turkish name in capitals, and a
 * record imported from a spreadsheet is in capitals throughout.
 *
 * Turkish is the case JavaScript gets wrong on its own. It has four letters
 * where English has two: dotted i and its capital, dotless i and its capital.
 * `toLowerCase()` sends the plain capital I to the dotted lower-case letter,
 * never to the dotless one, and sends the dotted capital to "i" followed by a
 * combining dot, so neither capitalised spelling of a Turkish word finds the
 * lower-case one. The strings below are escapes so that no editor, formatter
 * or diff can quietly swap one of the four for another.
 */
import { describe, it, expect } from 'vitest';

import { foldForSearch, matchesSearch } from '../highlightMatch';

const DOTTED_CAPITAL_I = 'İ';
const DOTLESS_SMALL_I = 'ı';

// "Istanbul" with the dotted capital, as the city is written in Turkish.
const ISTANBUL = `${DOTTED_CAPITAL_I}stanbul`;
// "isitma" (heating) as written in Turkish: two dotless letters.
const HEATING = `${DOTLESS_SMALL_I}s${DOTLESS_SMALL_I}tma`;
// "sinir" (boundary) as written in Turkish: dotless letters.
const BOUNDARY = `s${DOTLESS_SMALL_I}n${DOTLESS_SMALL_I}r`;

describe('the four Turkish letters compare equal in a search', () => {
  it('finds the dotted capital from a plain lower-case query', () => {
    expect(matchesSearch('istanbul', `${ISTANBUL} Veri Merkezi`)).toBe(true);
  });

  it('finds the dotless spelling from a query typed in capitals', () => {
    expect(matchesSearch('ISITMA', `Kat ${HEATING} tesisatı`)).toBe(true);
  });

  it('finds a record written in capitals from the dotless spelling', () => {
    expect(matchesSearch(HEATING, 'ISITMA TESİSATI')).toBe(true);
  });

  it('folds all four to one letter', () => {
    const folded = ['i', 'I', DOTTED_CAPITAL_I, DOTLESS_SMALL_I].map(foldForSearch);
    expect(new Set(folded).size).toBe(1);
    expect(folded[0]).toBe('i');
  });

  it('gives the same answer whatever language the interface is in', () => {
    // The fold takes no locale. A Turkish lower-casing would turn the plain
    // capitals below into the dotless spelling, and an English one into the
    // dotted spelling; the fold has to give one fixed answer, or the same
    // query finds a record for one colleague and not for the other.
    expect(foldForSearch('ISITMA')).toBe('isitma');
    expect(foldForSearch('ISITMA')).not.toBe('ISITMA'.toLocaleLowerCase('tr'));
    expect(foldForSearch(ISTANBUL)).toBe('istanbul');
    expect(foldForSearch(HEATING)).toBe('isitma');
  });

  it('also finds the neighbouring word, which is the price of the fold', () => {
    // "sinir" (nerve) and the dotless spelling (boundary) are different
    // words, and a query for one finds both. In a register filter the extra
    // row costs a glance, while a missed row costs the record.
    expect(matchesSearch('sinir', `Parsel ${BOUNDARY} duvarı`)).toBe(true);
    expect(matchesSearch(BOUNDARY, 'sinir')).toBe(true);
  });
});

describe('a query typed without diacritics finds the accented record, and back', () => {
  // s-cedilla, c-cedilla, g-breve, o-umlaut, u-umlaut, lower and upper.
  const PAIRS: Array<[string, string]> = [
    ['s', 'ş'],
    ['c', 'ç'],
    ['g', 'ğ'],
    ['o', 'ö'],
    ['u', 'ü'],
    ['S', 'Ş'],
    ['C', 'Ç'],
    ['G', 'Ğ'],
    ['O', 'Ö'],
    ['U', 'Ü'],
  ];

  it.each(PAIRS)('%s and %s match in both directions', (plain, accented) => {
    expect(matchesSearch(plain, `x${accented}x`)).toBe(true);
    expect(matchesSearch(accented, `x${plain}x`)).toBe(true);
  });

  it('finds a whole Turkish phrase from its phone-keyboard spelling', () => {
    // "Sogutma grubu cizimleri" against the correctly spelt record.
    const record = 'Soğutma grubu çizimleri';
    expect(matchesSearch('sogutma grubu cizimleri', record)).toBe(true);
    expect(matchesSearch('SOGUTMA GRUBU', record)).toBe(true);
  });
});

describe('other scripts still find themselves', () => {
  it('matches Cyrillic across case', () => {
    expect(matchesSearch('бетон', 'БЕТОН В3')).toBe(true);
    expect(matchesSearch('БЕТОН', 'товарный бетон')).toBe(true);
  });

  it('matches Greek across case, including a word ending in final sigma', () => {
    // "odos" in lower case ends in the final-sigma form; in capitals it does not.
    const lower = 'οδός';
    const upper = 'ΟΔΟΣ';
    expect(matchesSearch(upper, `${lower} 12`)).toBe(true);
    expect(matchesSearch(lower, `${upper} 12`)).toBe(true);
  });

  it('matches Arabic, with and without a hamza carrier, as itself', () => {
    const word = 'أعمال الخرسانة';
    expect(matchesSearch('الخرسانة', word)).toBe(true);
    expect(matchesSearch('أعمال', word)).toBe(true);
  });

  it('matches Chinese, Japanese and Korean as themselves', () => {
    expect(matchesSearch('混凝土', 'C30 混凝土墙')).toBe(true);
    // Katakana with a voiced mark, which decomposes to two code points.
    expect(matchesSearch('ガラス', '強化ガラス')).toBe(true);
    // Hangul, which decomposes to three.
    expect(matchesSearch('콘크리트', '철근 콘크리트')).toBe(true);
  });

  it('does not match a different word in those scripts', () => {
    expect(matchesSearch('木材', 'C30 混凝土墙')).toBe(false);
    expect(matchesSearch('кирпич', 'товарный бетон')).toBe(false);
  });

  it('keeps the German sharp s as one letter that matches itself in both cases', () => {
    const street = 'Hauptstraße 4';
    expect(matchesSearch('straße', street)).toBe(true);
    expect(matchesSearch('STRAẞE', street)).toBe(true);
    // It is not expanded to "ss": the fold keeps one character per character
    // so a match can be marked in the original text.
    expect(foldForSearch(street)).toHaveLength(street.length);
    expect(matchesSearch('strasse', street)).toBe(false);
  });
});

describe('the fold keeps one character per character', () => {
  it.each([
    `${ISTANBUL} ${HEATING}`,
    'Soğutma çizimleri',
    'οδός',
    '強化ガラス',
    '콘크리트',
    'Straße',
  ])('%s folds to the same number of characters', (text) => {
    expect(Array.from(foldForSearch(text))).toHaveLength(Array.from(text).length);
  });
});

describe('matchesSearch as a list filter', () => {
  it('matches everything on an empty or blank query', () => {
    expect(matchesSearch('', 'anything')).toBe(true);
    expect(matchesSearch('   ', null, undefined)).toBe(true);
  });

  it('skips missing fields instead of throwing on them', () => {
    expect(matchesSearch('pompa', null, undefined, '', 'Sirkülasyon pompası')).toBe(true);
    expect(matchesSearch('pompa', null, undefined, '')).toBe(false);
  });

  it('ignores the spaces around what was typed', () => {
    expect(matchesSearch('  pompa ', 'Sirkülasyon pompası')).toBe(true);
  });

  it('does not match across two fields', () => {
    expect(matchesSearch('ab', 'xa', 'bx')).toBe(false);
  });
});
