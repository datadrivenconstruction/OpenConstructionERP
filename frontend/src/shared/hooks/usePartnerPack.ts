// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * usePartnerPack — read the active partner pack manifest.
 *
 * Returns ``{ active: false }`` when no pack is installed; otherwise
 * returns the manifest the backend exposes at
 * ``/api/v1/partner-pack/current``. Cached for 5 minutes — the active
 * pack only changes when the operator changes ``OE_PARTNER_PACK`` and
 * restarts.
 */

import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/shared/lib/api';

export interface PartnerPackBranding {
  primary_color: string;
  accent_color: string | null;
  has_logo: boolean;
  has_favicon: boolean;
  powered_by_text: string;
}

/** Pack type under the Packs umbrella. The backend infers it from the
 *  manifest when it is not declared, and country metadata beats partner
 *  co-branding in that inference, so a partner pack written for one country
 *  resolves to ``country``. */
export type PackType = 'country' | 'industry' | 'partner' | 'showcase';

export interface PartnerPackManifest {
  slug: string;
  /** Absent on older backends; callers treat that as ``partner``. */
  type?: PackType;
  partner_name: string;
  partner_url: string | null;
  pack_version: string;
  description: string;
  default_locale: string;
  additional_locales: string[];
  cwicr_regions: string[];
  default_currency: string;
  default_tax_template: string | null;
  validation_rule_packs: string[];
  /** Rule-set ids the engine actually registers when the pack is applied.
   *  Not the same thing as `validation_rule_packs` above, which names the
   *  reference documents the pack ships and which the engine never executes.
   *  `to_public_dict` has always sent both; only this one answers "is anything
   *  checking my bills of quantities because of this pack". */
  validation_rule_sets: string[];
  default_modules: string[];
  hidden_modules: string[];
  /** The company profile this pack's users start in, or null. Absent on older
   *  backends. Read by the sidebar as the profile of a user who has chosen
   *  none (`effectiveCompanyPresetKey`). */
  default_company_profile?: string | null;
  branding: PartnerPackBranding;
  has_onboarding_script: boolean;
  metadata: Record<string, unknown>;
}

export interface PartnerPackResponse {
  active: boolean;
  manifest?: PartnerPackManifest;
}

/** ``GET /api/v1/partner-pack/installed`` — every pack this deployment holds. */
export interface InstalledPacksResponse {
  active_slug: string | null;
  installed: PartnerPackManifest[];
}

export function usePartnerPack() {
  return useQuery<PartnerPackResponse>({
    queryKey: ['partner-pack', 'current'],
    queryFn: () => apiGet<PartnerPackResponse>('/v1/partner-pack/current'),
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000,
    refetchOnWindowFocus: false,
  });
}

/**
 * Every regional pack installed here, not just the active one.
 *
 * ``usePartnerPack`` answers "which pack is switched on", which is the wrong
 * question for a screen that has a market in hand and wants to know whether a
 * pack serves it - a case study written for Germany is about Germany whether
 * or not the reader has applied a German pack today. This answers that one.
 *
 * Onboarding fetches the same endpoint through its own ``fetchInstalledPacks``
 * because it drives an install flow with streamed progress and needs the call
 * imperatively. This is the React Query reader for everyone else, and both go
 * to the same envelope, so the two cannot report different packs.
 */
export function useInstalledPacks() {
  return useQuery<InstalledPacksResponse>({
    queryKey: ['partner-pack', 'installed'],
    queryFn: () => apiGet<InstalledPacksResponse>('/v1/partner-pack/installed'),
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000,
    refetchOnWindowFocus: false,
  });
}

/**
 * Direct URL helper for the partner logo (no auth needed).
 *
 * Pass the active pack's ``slug`` to hit the by-slug endpoint, which resolves
 * the logo for BOTH pip-installed and source-checkout (in-app installed) packs.
 * The arg-less ``/logo`` endpoint only resolves pip-installed packs, so an
 * in-app one-click install would 404 and the badge ``<img>`` would break on
 * every page. Always pass the slug when you have it.
 */
export function partnerLogoUrl(slug?: string): string {
  return slug
    ? `/api/v1/partner-pack/logo/${encodeURIComponent(slug)}`
    : '/api/v1/partner-pack/logo';
}
