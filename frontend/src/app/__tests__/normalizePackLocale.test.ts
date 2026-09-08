// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// OpenConstructionERP — DataDrivenConstruction (DDC)
// Tests for normalizePackLocale: maps a partner pack's BCP-47 default_locale to
// a supported base UI language, so an active pack forces the right language
// (batimatech-ca -> fr) and never an unsupported one.
import { describe, expect, it } from 'vitest';

import { normalizePackLocale } from '../i18n';

describe('normalizePackLocale', () => {
  it('strips the region subtag when the UI does not ship that region', () => {
    expect(normalizePackLocale('fr-CA')).toBe('fr'); // batimatech-ca
    expect(normalizePackLocale('en-AU')).toBe('en'); // aus
    expect(normalizePackLocale('en-NZ')).toBe('en'); // nzs
  });

  it('keeps the region when the UI ships it, because the pack asked for it', () => {
    // A pack that names a region has named it deliberately. Stripping en-US left
    // commercial-denver asking for American English and being handed the British
    // strings, which is the one thing the locale exists to prevent.
    expect(normalizePackLocale('en-US')).toBe('en-US'); // commercial-denver, us-costdata
    // uk-jct and commercial-london both declare en-GB. This answered 'en'
    // until the UI started offering English (UK), and the pack was handed the
    // unqualified entry that names no region: American dates and prices under
    // a JCT contract. It moved up here the moment the region became something
    // the app could actually give it.
    expect(normalizePackLocale('en-GB')).toBe('en-GB');
    expect(normalizePackLocale('es-MX')).toBe('es-MX');
    expect(normalizePackLocale('pt-BR')).toBe('pt-BR'); // brazil-sinapi
    expect(normalizePackLocale('es-CL')).toBe('es-CL');
    expect(normalizePackLocale('es-CO')).toBe('es-CO');
  });

  it('passes through base codes the UI ships', () => {
    expect(normalizePackLocale('de')).toBe('de'); // bimhessen-de, doker-formwork
    expect(normalizePackLocale('pt')).toBe('pt'); // Portugal, no pack of its own
    expect(normalizePackLocale('ar')).toBe('ar'); // saudi-vision2030 (RTL)
    expect(normalizePackLocale('en')).toBe('en'); // india-cpwd, modular-prefab
  });

  it('is case-insensitive and trims', () => {
    expect(normalizePackLocale('FR-ca')).toBe('fr');
    expect(normalizePackLocale(' de ')).toBe('de');
    // A manifest is free to write the region in any case; i18next writes it in
    // one, and that is the one the resource bundle is registered under.
    expect(normalizePackLocale('en-us')).toBe('en-US');
    expect(normalizePackLocale('EN-US')).toBe('en-US');
    expect(normalizePackLocale(' en-Us ')).toBe('en-US');
  });

  it('falls back to English for unsupported or empty locales', () => {
    expect(normalizePackLocale('xx-YY')).toBe('en');
    expect(normalizePackLocale('')).toBe('en');
    expect(normalizePackLocale(null)).toBe('en');
    expect(normalizePackLocale(undefined)).toBe('en');
  });
});
