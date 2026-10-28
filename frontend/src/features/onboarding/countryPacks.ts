// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Curated Country Packs for one-click onboarding.
 *
 * A Country Pack bundles the localized building blocks a new workspace needs
 * for a given market into a single, install-it-all-at-once preset:
 *
 *   - locale          → the UI language code (i18next), e.g. ``de``
 *   - region          → a CWICR cost-database id (must exist in
 *                       ``CWICR_DATABASES`` in OnboardingWizard.tsx)
 *   - demoId          → a demo project id that is ALWAYS available from the
 *                       backend (a key of ``DEMO_TEMPLATES``)
 *   - classification  → the cost-classification standard recorded for the
 *                       workspace (DIN 276, NRM, MasterFormat, …)
 *
 * Region ids are NOT invented here — every ``region`` below is one of the
 * existing ``CWICR_DATABASES`` ids.
 *
 * Every preset carries a demo, and that is the point of the preset. It used to
 * say here that demo ids may only reference the five templates compiled into
 * ``demo_projects.py``, because the flagship demos under ``demo_packs/`` "only
 * register when their partner pack is installed". That is not what the code
 * does. ``demo_projects.py`` imports ``app.core.demo_packs`` unconditionally at
 * the bottom of the module, and the loader globs every pack file and merges it
 * into ``DEMO_TEMPLATES`` at import time. Nothing about it is conditional on a
 * pack being installed, applied or even present in ``packs/``.
 *
 * The claim cost sixteen of the twenty-one markets their example project. A
 * user picking Brazil, Japan or Poland was told the preset would set up sample
 * projects and then got a workspace with none, while the matching demo sat in
 * the registry the whole time. Measured before this was changed: a fresh
 * interpreter with no pack installed reports 38 templates and every id below
 * resolves. ``test_country_preset_demos_resolve.py`` asserts exactly that, so a
 * preset can no longer name a demo the backend does not have, and a demo can no
 * longer be assumed absent because a comment says so.
 */

/** Cost-classification standard a Country Pack records for the workspace. */
export type ClassificationStandard =
  | 'DIN276'
  | 'NRM'
  | 'MasterFormat'
  | 'CCS'
  | 'CWICR';

/** A single curated Country Pack preset. */
export interface CountryPack {
  /** Stable id, kebab-case, used as React key + analytics tag. */
  id: string;
  /** Display label for the country / market (English default value). */
  labelKey: string;
  /** Fallback English label, used as the i18next ``defaultValue``. */
  labelDefault: string;
  /** CountryFlag code (ISO-3166 alpha-2, lowercase). */
  flagId: string;
  /** UI language code (i18next). */
  locale: string;
  /** CWICR cost-database id — must exist in ``CWICR_DATABASES``. */
  region: string;
  /**
   * Demo project id, a key of the backend ``DEMO_TEMPLATES``.
   *
   * Not nullable, and deliberately so. A preset whose demo is missing is a
   * preset that quietly under-delivers what its own subtitle promises, which
   * is how sixteen markets ended up shipping without an example project. The
   * compiler now refuses that shape, and the backend test refuses an id the
   * registry cannot resolve.
   */
  demoId: string;
  /** Cost-classification standard recorded for the workspace. */
  classification: ClassificationStandard;
}

/**
 * Curated showcase + broad-spread Country Packs.
 *
 * Ordered roughly by market prominence so the picker leads with the markets
 * most operators ask for first (US, UK, DACH, France, …). Every ``region``
 * value is a verified ``CWICR_DATABASES`` id and every ``demoId`` is a
 * ``DEMO_TEMPLATES`` key, checked by a backend test rather than by eye.
 */
export const COUNTRY_PACKS: CountryPack[] = [
  // ── Showcase markets (lead the picker) ──────────────────────────────────
  {
    id: 'us',
    labelKey: 'onboarding.pack_us',
    labelDefault: 'United States',
    flagId: 'us',
    locale: 'en',
    region: 'USA_USD',
    demoId: 'medical-us',
    classification: 'MasterFormat',
  },
  {
    id: 'uk',
    labelKey: 'onboarding.pack_uk',
    labelDefault: 'United Kingdom',
    flagId: 'gb',
    locale: 'en',
    region: 'UK_GBP',
    demoId: 'office-london',
    classification: 'NRM',
  },
  {
    id: 'de',
    labelKey: 'onboarding.pack_de',
    labelDefault: 'Germany / DACH',
    flagId: 'de',
    locale: 'de',
    region: 'DE_BERLIN',
    demoId: 'residential-berlin',
    classification: 'DIN276',
  },
  {
    id: 'fr',
    labelKey: 'onboarding.pack_fr',
    labelDefault: 'France',
    flagId: 'fr',
    locale: 'fr',
    region: 'FR_PARIS',
    demoId: 'school-paris',
    classification: 'CWICR',
  },
  {
    id: 'br',
    labelKey: 'onboarding.pack_br',
    labelDefault: 'Brazil',
    flagId: 'br',
    locale: 'pt',
    region: 'PT_SAOPAULO',
    demoId: 'residential-saopaulo',
    classification: 'CWICR',
  },
  {
    id: 'ae',
    labelKey: 'onboarding.pack_ae',
    labelDefault: 'UAE / Gulf',
    flagId: 'ae',
    locale: 'ar',
    region: 'AR_DUBAI',
    demoId: 'warehouse-dubai',
    classification: 'MasterFormat',
  },
  {
    id: 'in',
    labelKey: 'onboarding.pack_in',
    labelDefault: 'India / South Asia',
    flagId: 'in',
    locale: 'hi',
    region: 'HI_MUMBAI',
    demoId: 'govt-building-delhi',
    classification: 'CWICR',
  },
  {
    id: 'cn',
    labelKey: 'onboarding.pack_cn',
    labelDefault: 'China',
    flagId: 'cn',
    locale: 'zh',
    region: 'ZH_SHANGHAI',
    demoId: 'office-shanghai',
    classification: 'CCS',
  },
  // ── Broad spread across CWICR_DATABASES ─────────────────────────────────
  {
    id: 'ca',
    labelKey: 'onboarding.pack_ca',
    labelDefault: 'Canada',
    flagId: 'ca',
    locale: 'en',
    region: 'ENG_TORONTO',
    demoId: 'condo-toronto',
    classification: 'MasterFormat',
  },
  {
    id: 'au',
    labelKey: 'onboarding.pack_au',
    labelDefault: 'Australia',
    flagId: 'au',
    locale: 'en',
    region: 'AU_SYDNEY',
    demoId: 'mixed-use-sydney',
    classification: 'NRM',
  },
  {
    id: 'nz',
    labelKey: 'onboarding.pack_nz',
    labelDefault: 'New Zealand',
    flagId: 'nz',
    locale: 'en',
    region: 'NZ_AUCKLAND',
    demoId: 'commercial-auckland',
    classification: 'NRM',
  },
  {
    id: 'it',
    labelKey: 'onboarding.pack_it',
    labelDefault: 'Italy',
    flagId: 'it',
    locale: 'it',
    region: 'IT_ROME',
    demoId: 'residential-rome',
    classification: 'CWICR',
  },
  {
    id: 'es',
    labelKey: 'onboarding.pack_es',
    labelDefault: 'Spain / Latin America',
    flagId: 'es',
    locale: 'es',
    region: 'SP_BARCELONA',
    demoId: 'mixed-use-barcelona',
    classification: 'CWICR',
  },
  {
    id: 'nl',
    labelKey: 'onboarding.pack_nl',
    labelDefault: 'Netherlands',
    flagId: 'nl',
    locale: 'nl',
    region: 'NL_AMSTERDAM',
    demoId: 'office-amsterdam',
    classification: 'CWICR',
  },
  {
    id: 'pl',
    labelKey: 'onboarding.pack_pl',
    labelDefault: 'Poland',
    flagId: 'pl',
    locale: 'pl',
    region: 'PL_WARSAW',
    demoId: 'residential-warsaw',
    classification: 'CWICR',
  },
  {
    id: 'tr',
    labelKey: 'onboarding.pack_tr',
    labelDefault: 'Türkiye',
    flagId: 'tr',
    locale: 'tr',
    region: 'TR_ISTANBUL',
    demoId: 'mixed-use-istanbul',
    classification: 'CWICR',
  },
  {
    id: 'ru',
    labelKey: 'onboarding.pack_ru',
    labelDefault: 'Russia / CIS',
    flagId: 'ru',
    locale: 'ru',
    region: 'RU_STPETERSBURG',
    demoId: 'school-stpetersburg',
    classification: 'CWICR',
  },
  {
    id: 'jp',
    labelKey: 'onboarding.pack_jp',
    labelDefault: 'Japan',
    flagId: 'jp',
    locale: 'ja',
    region: 'JA_TOKYO',
    demoId: 'office-tokyo',
    classification: 'CWICR',
  },
  {
    id: 'kr',
    labelKey: 'onboarding.pack_kr',
    labelDefault: 'South Korea',
    flagId: 'kr',
    locale: 'ko',
    region: 'KO_SEOUL',
    demoId: 'residential-seoul',
    classification: 'CWICR',
  },
  {
    id: 'mx',
    labelKey: 'onboarding.pack_mx',
    labelDefault: 'Mexico',
    flagId: 'mx',
    locale: 'es',
    region: 'MX_MEXICOCITY',
    demoId: 'mixed-use-mexico-city',
    classification: 'CWICR',
  },
  {
    id: 'za',
    labelKey: 'onboarding.pack_za',
    labelDefault: 'South Africa',
    flagId: 'za',
    locale: 'en',
    region: 'ZA_JOHANNESBURG',
    demoId: 'mixed-use-johannesburg',
    classification: 'NRM',
  },
];

/** A Country Pack id, derived from the curated list. */
export type CountryPackId = (typeof COUNTRY_PACKS)[number]['id'];

/**
 * The default Country Pack (United States) — a guaranteed-present fallback so
 * callers never have to handle ``undefined`` from an empty list under
 * ``noUncheckedIndexedAccess``.
 */
export const DEFAULT_COUNTRY_PACK: CountryPack = COUNTRY_PACKS[0] ?? {
  id: 'us',
  labelKey: 'onboarding.pack_us',
  labelDefault: 'United States',
  flagId: 'us',
  locale: 'en',
  region: 'USA_USD',
  demoId: 'medical-us',
  classification: 'MasterFormat',
};

/** Look up a Country Pack by id. */
export function getCountryPack(id: string): CountryPack | undefined {
  return COUNTRY_PACKS.find((p) => p.id === id);
}
