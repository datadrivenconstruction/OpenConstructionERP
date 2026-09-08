// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every user-visible string a first-party manifest declares has to be
// translatable, and the translation has to exist.
//
// The regression this pins is a slow one: a manifest ships an English literal
// where the contract says i18n key, no gate can see it because the type is
// `string` either way, and the module keeps its English name in all 40
// languages for as long as nobody opens the registry page in German. Shape
// alone would not catch the other half of it, so each key is also resolved:
// a key nothing answers renders as the key on screen, which is worse than the
// literal it replaced.
//
// Run:  npx vitest run src/modules/manifestI18n.test.ts

import { describe, it, expect } from 'vitest';

import de from '../app/locales/de';
import en from '../app/locales/en';
import { MODULE_REGISTRY } from './_registry';
import { isModuleI18nKey } from './_i18n';
import type { ModuleManifest } from './_types';

/** Where a manifest string is declared, for a failure message that locates it. */
interface ManifestString {
  moduleId: string;
  field: string;
  value: string;
  manifest: ModuleManifest;
}

const NAMES_AND_DESCRIPTIONS: ManifestString[] = MODULE_REGISTRY.flatMap((m) => [
  { moduleId: m.id, field: 'name', value: m.name, manifest: m },
  { moduleId: m.id, field: 'description', value: m.description, manifest: m },
]);

const ROUTE_TITLES: ManifestString[] = MODULE_REGISTRY.flatMap((m) =>
  m.routes.map((r) => ({
    moduleId: m.id,
    field: `route ${r.path} title`,
    value: r.title,
    manifest: m,
  })),
);

/**
 * The one module whose country route titles stay English literals: a country
 * label names a measurement standard and carries its country with it
 * ("United Kingdom NRM 1/2"), and the standard half is not translated in any
 * language. Its hub route is keyed like every other title, because the hub
 * speaks for the module and not for a standard. Named here rather than
 * skipped silently, so the exception stays a closed set of exactly one module
 * and a new literal anywhere else fails.
 */
const LITERAL_ROUTE_TITLE_MODULES = new Set(['regional-exchange']);

/** English for a key: the locale file first, then the module's own bundle. */
function englishFor(entry: ManifestString): string | undefined {
  return en.translation[entry.value] ?? entry.manifest.translations?.['en']?.[entry.value];
}

/** German for a key, from the same two sources. */
function germanFor(entry: ManifestString): string | undefined {
  return de.translation[entry.value] ?? entry.manifest.translations?.['de']?.[entry.value];
}

describe('manifest names and descriptions', () => {
  it('are i18n keys, never English literals', () => {
    const literals = NAMES_AND_DESCRIPTIONS.filter((e) => !isModuleI18nKey(e.value)).map(
      (e) => `${e.moduleId}.${e.field} = ${JSON.stringify(e.value)}`,
    );
    expect(literals).toEqual([]);
  });

  it('name a key that English answers', () => {
    // Either the locale files carry it, or the manifest ships it itself. Both
    // are legitimate; having neither means the registry page renders the raw
    // key to every reader, English included.
    const unanswered = NAMES_AND_DESCRIPTIONS.filter((e) => !englishFor(e)).map(
      (e) => `${e.moduleId}.${e.field} -> ${e.value}`,
    );
    expect(unanswered).toEqual([]);
  });

  it('name a key that German answers', () => {
    // German is the pilot market and the one language every module string is
    // held to. A key present only in English silently falls back, and the
    // fallback looks exactly like a translation that was never needed.
    const unanswered = NAMES_AND_DESCRIPTIONS.filter((e) => !germanFor(e)).map(
      (e) => `${e.moduleId}.${e.field} -> ${e.value}`,
    );
    expect(unanswered).toEqual([]);
  });

  it('are actually translated in German, not the English string again', () => {
    // A module-carried "translation" that repeats the English is the failure
    // this whole sweep is about, just moved one file over. Proper nouns are
    // the honest exception: a standard or product name reads the same in both
    // languages, so only strings with no such name are held to it.
    const PROPER_NOUNS = /GAEB|COLLADA|DataFrame|IFC|RVT|BOQ|EPD|Yjs|CRDT|Monte Carlo|DIN|NRM/;
    const untranslated = NAMES_AND_DESCRIPTIONS.filter((e) => {
      const english = englishFor(e);
      return english && !PROPER_NOUNS.test(english) && germanFor(e) === english;
    }).map((e) => `${e.moduleId}.${e.field} -> ${e.value}`);
    expect(untranslated).toEqual([]);
  });

  it('are actually translated in every locale a manifest carries, not the English string again', () => {
    // Generalizes the German check above to every locale any manifest ships
    // a translation for, rather than pinning German alone. A manifest-carried
    // locale that repeats the English string is the same failure as the
    // German case, just for a language nobody happened to open the registry
    // page in yet - and this keeps working for whatever locale a manifest
    // adds next, not only the ones present today.
    const PROPER_NOUNS = /GAEB|COLLADA|DataFrame|IFC|RVT|BOQ|EPD|Yjs|CRDT|Monte Carlo|DIN|NRM/;
    const untranslated: string[] = [];
    for (const entry of NAMES_AND_DESCRIPTIONS) {
      const english = englishFor(entry);
      if (!english || PROPER_NOUNS.test(english)) continue;
      const locales = Object.keys(entry.manifest.translations ?? {});
      for (const lng of locales) {
        if (lng === 'en' || lng === 'de') continue; // covered by the test above
        const value = entry.manifest.translations?.[lng]?.[entry.value];
        if (value !== undefined && value === english) {
          untranslated.push(`${entry.moduleId}.${entry.field} -> ${entry.value} [${lng}]`);
        }
      }
    }
    expect(untranslated).toEqual([]);
  });
});

describe('module route titles', () => {
  it('are i18n keys outside the one module that names standards', () => {
    const literals = ROUTE_TITLES.filter(
      (e) => !isModuleI18nKey(e.value) && !LITERAL_ROUTE_TITLE_MODULES.has(e.moduleId),
    ).map((e) => `${e.moduleId} ${e.field} = ${JSON.stringify(e.value)}`);
    expect(literals).toEqual([]);
  });

  it('keep the exception to the modules that declare it', () => {
    // If regional-exchange ever keys its country titles too, this fails and
    // the exception above gets deleted rather than quietly outliving its
    // reason. Its hub route is keyed already, so the question is whether any
    // literal is left, not whether every title is one.
    for (const moduleId of LITERAL_ROUTE_TITLE_MODULES) {
      const titles = ROUTE_TITLES.filter((e) => e.moduleId === moduleId);
      expect(titles.length, `${moduleId} declares no routes`).toBeGreaterThan(0);
      expect(
        titles.some((e) => !isModuleI18nKey(e.value)),
        `${moduleId} keys every title now, delete the exception`,
      ).toBe(true);
    }
  });

  it('name a key both English and German answer', () => {
    const keyed = ROUTE_TITLES.filter((e) => isModuleI18nKey(e.value));
    expect(keyed.length).toBeGreaterThan(0);
    const unanswered = keyed
      .filter((e) => !englishFor(e) || !germanFor(e))
      .map((e) => `${e.moduleId} ${e.field} -> ${e.value}`);
    expect(unanswered).toEqual([]);
  });
});
