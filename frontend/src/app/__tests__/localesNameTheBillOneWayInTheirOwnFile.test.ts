import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * The sibling gate, localesNameTheBillTheWayTheTradeDoes, holds six locales to
 * a name chosen for them: German writes LV, French DQE, Italian computo
 * metrico. That gate cannot grow past those six without someone deciding what
 * the rest should say, and deciding that is inventing terminology rather than
 * restoring it.
 *
 * This gate asks a question that needs no such decision. Every locale already
 * answers "what is this object called" in its own file: the label the module
 * catalogue puts in the navigation. So the question is not whether the locale
 * uses the right name, it is whether the locale uses the SAME name twice. A
 * file that calls the object one thing in the navigation and a second, equally
 * plausible thing two screens later has the disease the sibling gate was
 * written for, and it has it in a language nobody here can adjudicate.
 *
 * It is a floor, not a standard. The twenty divergences that predate it,
 * across seventeen locales and three keys, are recorded below with the locale
 * named, and the baseline may only shrink. Both directions are checked, in
 * two separate tests per key so that the failure says which way it went: a new
 * divergence is the gate proper, and a baselined locale that has been fixed is
 * a list gone stale, which is red because the answer is to delete the line and
 * not to undo the translation. Recording a locale here does not say its catalogue label is
 * the right name. In several it is the other way round - Czech výkaz výměr and
 * Dutch hoeveelhedenstaat are the settled trade terms while the catalogue
 * label reads closer to "budget" - and which of the two moves is a question
 * for a native speaker, not for a test.
 *
 * The seventeen on validation.subtitle at the time this gate landed were
 * arrived at twice, by two methods sharing no code: a stem and inflection
 * reading of each pair, which accepts Turkish keşif özetini for keşif özeti,
 * and the normalised substring containment this file implements. Both named
 * the same seventeen locales, so doubting the list meant doubting two
 * instruments rather than one. Urdu was one of the seventeen and is no longer
 * baselined below: its divergence was not a second name, it was a hole.
 * `.i18n-work/ur/_glossary.md` records "Bill of Quantities" as translated to
 * مقدار کا بل (BOQ) everywhere, the catalogue label already carries that
 * string, and validation.subtitle alone had left the English in place. There
 * was no second term to adjudicate, so this one moved without a native
 * speaker, unlike the sixteen still recorded below.
 *
 * What the containment rule cannot see: where the catalogue label is a generic
 * word for money on a page - Raming, Rozpočet, Kosztorys, Presupuesto - any
 * occurrence of that word anywhere in the value satisfies the check, including
 * in a sentence that also names the bill something else. Those are exactly the
 * locales whose label is most likely to be the wrong half of the pair. This
 * gate locks the floor where it found it; it does not prove that the locales
 * outside the baseline name the object once. Filipino is the clearest case:
 * it passes because its catalogue label and its subtitle both read the English
 * phrase verbatim, which is internal consistency and not a translation.
 */

const RESOLVED = ['src/app/locales', 'frontend/src/app/locales']
  .map((p) => resolve(process.cwd(), p))
  .find(existsSync);
if (!RESOLVED) {
  throw new Error(
    'no locale directory at src/app/locales or frontend/src/app/locales: run this from frontend or from the repository root',
  );
}

/**
 * Narrowed once here rather than cast at each use. A cast only silences the
 * compiler, and the undefined it hides would arrive at the readdirSync below,
 * which runs while the file is being collected rather than inside a test. A
 * collection error takes the whole file down, and vitest reports that as no
 * tests, which reads like nothing to check rather than like a broken
 * instrument. Failing here instead costs one line and names the cause.
 */
const LOCALES_DIR = RESOLVED;

/** `  "key": "value",` - the shape every line in a locale file has. */
const PAIR = /^\s*"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,?\s*$/;

/** The locale's own answer to what the object is called. */
const CATALOGUE = 'modules.catalog.boq';

/**
 * Keys that name the object rather than refer to it. Deliberately short.
 * Most keys mentioning the bill in English do not name it in translation -
 * they say "it", or drop the noun - so containment there measures sentence
 * shape and not naming: of the 880 keys whose English value says BOQ or bill
 * of quantities, containment would call 23679 of 35977 translated values a
 * divergence. Measured, not estimated. These three are the keys where the
 * locale names the object instead of referring to it.
 */
const NAMING_KEYS = ['nav.boq', 'boq.title', 'validation.subtitle'] as const;

/**
 * The short form a locale uses where the full catalogue label would be
 * clumsy. Only the six locales the sibling gate already holds to a reviewed
 * name are here, and this is a division of labour rather than a loophole:
 * those six are checked far more tightly next door, including for rival names
 * and for the grammar the name governs. Each pattern is pinned below to still
 * match its own catalogue label, so a locale that renames the object in the
 * navigation cannot leave a stale short form behind.
 */
const SHORT_FORMS: Record<string, RegExp> = {
  de: /\bLV\b|LV-|Leistungsverzeichnis/,
  fr: /\bDQE\b|devis quantitatifs?/i,
  it: /comput[oi] metric[io]/i,
  zh: /工程量清单/,
  ja: /内訳書/,
  ko: /내역서/,
};

/**
 * Locales already naming the object twice when this gate landed, per key,
 * with what the divergent value calls it. Shrinks only, and every line needs
 * the second name written out: a divergence nobody described is indefensible
 * to remove later, because the next reader cannot tell whether it was fixed
 * or merely reworded.
 *
 * Arabic and Persian carry their second name in a right-to-left script, and
 * pasting it into a comment reorders the whole line in most editors, so those
 * two are described in English instead of quoted.
 */
const BASELINE: Record<(typeof NAMING_KEYS)[number], Record<string, string>> = {
  'nav.boq': {
    // The navigation itself disagrees with the catalogue two entries away.
    ky: 'Смета ведомосу against the catalogue Иш көлөмдөрүнүн тизмеси',
  },
  'boq.title': {
    // Not a second name for the same object: this one says list of materials.
    ky: 'Материалдардын тизмеси, which is the bill of materials',
    ro: 'Antemăsurătoare, the settled Romanian trade term',
    th: 'ปริมาณงาน, the catalogue label with its first word dropped',
  },
  'validation.subtitle': {
    ar: 'a statement of quantities where the catalogue says a table of quantities',
    bn: 'পরিমাণ তালিকা where the catalogue transliterates the English name',
    cs: 'výkaz výměr, the settled Czech trade term, against the catalogue Rozpočet',
    da: 'mængdefortegnelse against the catalogue Tilbudsliste',
    el: 'Επιμέτρηση Ποσοτήτων against the catalogue Πίνακας Ποσοτήτων',
    fa: 'a progress-statement word in front of quantities, a third name in this file',
    hi: 'बिल ऑफ क्वांटिटीज़, the English name transliterated',
    id: 'daftar volume pekerjaan against the catalogue Daftar Kuantitas',
    kk: 'Жұмыс көлемдерінің тізілімі against the catalogue Көлемдер Ведомостісі',
    ky: 'көлөм ведомосу, a third name in this file',
    mn: 'Тоо хэмжээний жагсаалт against the catalogue Ажил материалын жагсаалт',
    nl: 'hoeveelhedenstaat, the settled Dutch trade term, against the catalogue Raming',
    no: 'mengdebeskrivelse against the catalogue Mengdefortegnelse',
    pl: 'przedmiar robót, the settled Polish trade term, against the catalogue Kosztorys',
    pt: 'mapa de quantidades against the catalogue Planilha Orçamentária',
    th: 'บัญชีแสดงปริมาณงาน against the catalogue บัญชีปริมาณงาน',
  },
};

function read(code: string): Map<string, string> {
  const values = new Map<string, string>();
  for (const line of readFileSync(resolve(LOCALES_DIR, `${code}.ts`), 'utf8').split(/\r?\n/)) {
    const [, key, value] = PAIR.exec(line) ?? [];
    if (key !== undefined && value !== undefined) values.set(key, value);
  }
  return values;
}

/**
 * Every locale but the source. en is what the others are translated from, so
 * it cannot disagree with itself; en-US stays in, because it is a 1580 key
 * overlay that renames this very object to Bid Schedule and is exactly the
 * kind of file where half a rename would survive unnoticed.
 */
const CODES = readdirSync(LOCALES_DIR)
  .filter((file) => file.endsWith('.ts'))
  .map((file) => file.replace(/\.ts$/, ''))
  .filter((code) => code !== 'en')
  .sort();

const VALUES = new Map(CODES.map((code) => [code, read(code)] as const));

/** A bracket holding only the loan word glosses the name, it is not the name. */
const LOAN_GLOSS = /\s*[（(]\s*[Bb][Oo][Qq]s?\s*[)）]\s*/g;

const normalise = (value: string) =>
  value.normalize('NFC').replace(LOAN_GLOSS, ' ').replace(/\s+/g, ' ').trim().toLocaleLowerCase();

function namesTheBill(code: string, value: string, catalogue: string): boolean {
  const short = SHORT_FORMS[code];
  if (short) return short.test(value);
  return normalise(value).includes(normalise(catalogue));
}

function divergent(key: string): string[] {
  const found: string[] = [];
  for (const [code, values] of VALUES) {
    const catalogue = values.get(CATALOGUE);
    const value = values.get(key);
    if (!catalogue || !value) continue;
    if (!namesTheBill(code, value, catalogue)) found.push(code);
  }
  return found.sort();
}

const carrying = (key: string) => CODES.filter((code) => VALUES.get(code)?.has(key)).length;

describe('every locale names the bill one way inside its own file', () => {
  it('reads a population big enough for the answer to mean anything', () => {
    // A gate that quietly narrows its question passes on every tree. The
    // numbers are floors, not counts, because locales get added.
    expect(CODES.length).toBeGreaterThanOrEqual(40);
    expect(NAMING_KEYS.length).toBeGreaterThanOrEqual(3);
    const thin = NAMING_KEYS.filter((key) => carrying(key) < 30).map(
      (key) => `${key}: only ${carrying(key)} of ${CODES.length} locales carry it`,
    );
    expect(thin).toEqual([]);
  });

  it('has a catalogue label to compare against in every locale that names the bill', () => {
    // The whole gate hangs off this key. A locale that carries one of the
    // naming keys and not the label is not consistent, it is unmeasured, and
    // divergent() would skip it in silence.
    const names = (code: string) => NAMING_KEYS.some((key) => VALUES.get(code)?.has(key));
    expect(CODES.filter((code) => names(code) && !VALUES.get(code)?.get(CATALOGUE))).toEqual([]);
  });

  it('exempts only an overlay that names the bill nowhere, and names it', () => {
    // en-GB carries nine British spellings and not one of them is this object,
    // so there is nothing in it to compare and nothing for it to disagree
    // with: every bill key a British reader sees comes from en.ts. The list is
    // written out so a full locale that lost every naming key reads as the
    // hole it is rather than as a second exemption.
    const silent = CODES.filter((code) => !NAMING_KEYS.some((key) => VALUES.get(code)?.has(key)));
    expect(silent).toEqual(['en-GB']);
  });

  for (const key of NAMING_KEYS) {
    it(`${key} calls the bill what the module catalogue calls it`, () => {
      // The gate proper: a locale naming the object a second way that nobody
      // has written down yet.
      expect(divergent(key).filter((code) => !(code in BASELINE[key]))).toEqual([]);
    });

    it(`${key} keeps its baseline describing the tree`, () => {
      // The other direction, split out rather than folded into one exact-set
      // comparison so that the failure says which way it went. A list that
      // keeps a locale after the locale is fixed stops describing the tree and
      // starts excusing it, and the next reader cannot tell which entries are
      // still real. When this fails, delete the named locale from BASELINE.
      // Never undo the translation that fixed it.
      expect(Object.keys(BASELINE[key]).filter((code) => !divergent(key).includes(code))).toEqual([]);
    });
  }

  it('keeps every short form pinned to the label it is short for', () => {
    const stale = Object.entries(SHORT_FORMS)
      .filter(([code, pattern]) => {
        const catalogue = VALUES.get(code)?.get(CATALOGUE);
        return !catalogue || !pattern.test(catalogue);
      })
      .map(([code]) => code);
    expect(stale).toEqual([]);
  });

  it('sees a locale that swaps in a second name of its own', () => {
    // The Dutch shape, which is what eleven of the eighteen look like.
    expect(namesTheBill('nl', 'Controleer een hoeveelhedenstaat tegen de regelsets.', 'Raming')).toBe(false);
    expect(namesTheBill('nl', 'Controleer een raming tegen de regelsets.', 'Raming')).toBe(true);
  });

  it('sees a locale that drops its own name for the loan word', () => {
    expect(namesTheBill('pl', 'Sprawdź BOQ względem zestawów reguł.', 'Kosztorys')).toBe(false);
    // A bracket holding only the loan word is a gloss on the name, and the
    // name is still there in front of it.
    expect(namesTheBill('pl', 'Sprawdź kosztorys (BOQ) względem zestawów reguł.', 'Kosztorys')).toBe(true);
  });

  it('lets the six locales the sibling gate holds use their short form', () => {
    expect(namesTheBill('de', 'Projekt und LV auswählen', 'Leistungsverzeichnis')).toBe(true);
    expect(namesTheBill('it', 'Controlla un computo metrico', 'Computo metrico estimativo')).toBe(true);
    // And it is a short form, not a free pass: a rival name still fails.
    expect(namesTheBill('de', 'Projekt und Kostengruppe auswählen', 'Leistungsverzeichnis')).toBe(false);
  });
});
