// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The world exchange catalogue, as the hub reads it.
 *
 * The list of markets and formats is served by the backend
 * (`GET /v1/boq/boqs/exchange-formats/`) rather than written here, and that
 * is the whole point of the endpoint. Whether a format can be read or
 * written is decided by which importers and exporters are registered in
 * Python; a copy of that answer living in TypeScript would be right on the
 * day it was written and wrong from the next commit onwards, with nothing
 * to catch it, because a screen that promises an import nobody implemented
 * fails at the user rather than in a test.
 *
 * What this file does own is the part the backend cannot know: which
 * market the reader is probably in, and which of our own screens knows a
 * given market's paperwork in more detail than the generic panel does.
 */

import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/shared/lib/api';
import { COUNTRY_TEMPLATES, type RegionalTemplate } from './regionalRegistry';

/** How well the product handles one direction of one format. */
export type SupportLevel = 'native' | 'assisted' | 'none';

/** One row of the catalogue, exactly as the backend sends it. */
export interface ExchangeFormatInfo {
  format_id: string;
  name: string;
  countries: string[];
  extensions: string[];
  summary: string;
  standard: string;
  rule_packs: string[];
  header_language: string | null;
  import_support: SupportLevel;
  export_support: SupportLevel;
  /** Path under `/boqs/{boq_id}/` that serves an export, when we write it. */
  export_route: string | null;
  export_extension: string | null;
  export_media_type: string | null;
}

export interface ExchangeCatalogue {
  formats: ExchangeFormatInfo[];
  country: string | null;
  default_format_id: string | null;
  header_languages: string[];
}

/**
 * Every upload goes to the dispatcher, whatever the user picked.
 *
 * The format buttons choose what the screen explains and what an export
 * produces; they deliberately do not choose the reader. The dispatcher
 * sniffs the file and answers with the format it actually recognised, so
 * a person who picks their own market and then drops a file a colleague
 * sent from another market gets it imported and gets told which format it
 * turned out to be. A picker that routed the upload would instead fail,
 * and blame them for the mistake of being sent the wrong file.
 */
export const IMPORT_ENDPOINT = (boqId: string): string => `/api/v1/boq/boqs/${boqId}/import/auto/`;

/** Absolute URL for an export, built from what the catalogue reported. */
export function exportEndpoint(boqId: string, format: ExchangeFormatInfo): string | null {
  if (!format.export_route) return null;
  return `/api/v1/boq/boqs/${boqId}/${format.export_route}/`;
}

export function useExchangeCatalogue(country: string | null) {
  return useQuery<ExchangeCatalogue>({
    queryKey: ['exchange-catalogue', country ?? ''],
    queryFn: () =>
      apiGet<ExchangeCatalogue>(
        country ? `/v1/boq/boqs/exchange-formats/?country=${encodeURIComponent(country)}` : '/v1/boq/boqs/exchange-formats/',
      ),
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * The market this reader is probably working in, or null.
 *
 * Deliberately a preselection and never a filter. Every market stays on
 * the page whatever this returns, because the common reason to open this
 * screen at all is that somebody sent you a file from somewhere else.
 *
 * Order of evidence, strongest first:
 *
 * 1. The country on the open project. It is a fact about the work, stated
 *    by whoever set the project up.
 * 2. The region in the reader's own language tag, when the tag carries
 *    one (`de-AT`, `pt-BR`, `es-MX`). Also a statement, just a weaker one.
 * 3. The region a bare language tag implies (`de` implies Germany, `ru`
 *    Russia). This is the only guess in the chain, and it is the one that
 *    is wrong for an Austrian who has their interface in German, which is
 *    exactly why the answer is offered as a highlighted button rather than
 *    applied silently.
 */
export function inferMarket(projectCountry: string | null | undefined, language: string): string | null {
  const fromProject = (projectCountry ?? '').trim().toUpperCase();
  if (/^[A-Z]{2}$/.test(fromProject)) return fromProject;

  const tag = (language || '').trim();
  if (!tag) return null;

  const explicit = tag.split('-')[1];
  if (explicit && /^[A-Za-z]{2}$/.test(explicit)) return explicit.toUpperCase();

  try {
    // `maximize()` fills in the region a language is most used in. It is a
    // published mapping rather than a table we would have to keep, and it
    // answers for every language rather than for the dozen someone
    // remembered.
    const region = new Intl.Locale(tag).maximize().region;
    if (region && /^[A-Z]{2}$/.test(region)) return region;
  } catch {
    // An unparsable tag is not worth an error; the reader picks a market.
  }
  return null;
}

/**
 * The dedicated screen for a market, where one exists.
 *
 * Twenty markets have a page that knows their trade-section breakdown,
 * their classification code shape and their column layout. The generic
 * panel on the hub cannot do those things, so where such a page exists the
 * hub links to it rather than pretending to replace it.
 *
 * Matched on the country code and never on the format, because the
 * specialist pages are organised by market and several of them accept more
 * than one format.
 */
export function specialistPageFor(country: string | null): RegionalTemplate | null {
  if (!country) return null;
  const code = country.toUpperCase();
  return COUNTRY_TEMPLATES.find((tpl) => tpl.countryCode.toUpperCase() === code) ?? null;
}

/** Every market the catalogue names, deduplicated. */
export function marketsIn(formats: ExchangeFormatInfo[]): string[] {
  const seen = new Set<string>();
  for (const fmt of formats) for (const code of fmt.countries) seen.add(code);
  return [...seen];
}

/**
 * The formats to show for a market, best first.
 *
 * Within a market the catalogue's own order is kept, because it is
 * meaningful: the backend lists a market's real interchange container
 * ahead of its workbook and the workbook ahead of the formats that belong
 * to nobody. What is added here is only the tail, the formats that belong
 * to every market, so that a reader who wants a plain spreadsheet always
 * finds one without leaving their own market's view.
 */
export function formatsForMarket(formats: ExchangeFormatInfo[], country: string | null): ExchangeFormatInfo[] {
  if (!country) return formats;
  const code = country.toUpperCase();
  const mine = formats.filter((fmt) => fmt.countries.includes(code));
  const universal = formats.filter((fmt) => fmt.countries.length === 0);
  return [...mine, ...universal];
}
