// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - photography plumbing shared by every future card/picker variant.
//
// The marketing site already puts a person on every case card and detail hero
// (marketing-site/scripts/put_case_face.py). This module mirrors that script's
// casting logic so the app and the site show the SAME person for the same
// company type: `ROLE_CAST` is copied verbatim from the script's ROLE_CAST,
// and `caseFaceFor` reproduces its `deal()` round-robin (position within the
// company type, `cast[index % cast.length]`).
//
// The mirror is of the script's LOGIC, not of its current behaviour. That
// script reads the first `data-roles` token off the gallery and looks it up in
// ROLE_CAST, which is keyed by company types; since the site split the two
// axes, `data-roles` holds professions and fourteen of the fifteen have nobody
// cast. Do not "restore parity" by making this module read `Playbook.roles` -
// the axis here is the correct one, and the divergence is on the other side.
//
// The images live under `frontend/public/assets/people/` and are addressed by
// runtime path strings on purpose: 133 webp files as Vite imports would bloat
// the module graph, while public-dir paths stay lazy and cacheable.
//
//   prf-*.webp  340x480 role portraits (the pooled cast)
//   cmp-*.webp  340x480 company scenes (the site, not a person)
//   cmt-*.webp  128x128 square crops of those scenes, for small tiles
//   pbk-*.webp  200x300 bespoke photos for ten flagship cases
//
// COUNTRY VARIANTS. A case authored for one market (`Playbook.region`, an
// uppercase ISO 3166-1 alpha-2 code) prefers a portrait shot for that market:
//
//   prf-<country>-*.webp  340x480, e.g. prf-de-commercial-manager.webp
//
// The country code is lowercased, because every filename in that folder is
// lowercase and a Linux server does not forgive what Windows does.
//
// The variant decorates the stem the pooled casting ALREADY chose - company
// type first, then the positional round-robin - rather than replacing the
// choice. That is what keeps the anti-repeat guarantee: the thirteen German
// general-contractor cases still wear eight different people, each of them
// German, instead of collapsing onto one national face per company type.
//
// Which country files exist is READ off the folder, not discovered by asking
// for them. `countryPortraits.generated.ts` lists the `prf-<cc>-*.webp` that
// are actually there; scripts/gen_case_country_portraits.py writes it out of
// public/assets/people, and this module asks for a country portrait only when
// that list says one was bought. Adding art stays a folder operation - drop
// the webp in, run the script - and no filename is ever typed into TypeScript
// by hand.
//
// The trap `COMPANY_ART_IDS` in CompanyArt.tsx is still sitting in is a list
// MAINTAINED by hand: an empty set gating a path that nothing compares to the
// disk. A list DERIVED from the disk, with a test that fails when the two
// disagree in either direction, is the same open set with the discovery moved
// off the network. The version of this module that shipped without a manifest
// let the browser find out instead, which sounds cheaper and was not: with no
// country art bought yet, every render of the hub, the case page and the
// dashboard gallery spent 61 image requests learning that the folder is empty,
// changed nothing on screen, and left 61 4xx lines in front of whoever opened
// the console.
//
// The browser still gets the last word. `CaseFace` carries the pooled portrait
// beside the requested one and `CaseFacePhoto` swaps to it on the error event,
// because the manifest is generated at commit time: a deploy that ships the
// list without the webp, or loses the webp afterwards, has to land on a
// picture rather than a broken-image glyph.
//
// Bespoke `pbk-*` photos stay country-blind. They are shot for one named case,
// and a case belongs to one market at most, so the country is already in the
// picture; a `pbk-de-*` would be the same photograph under a longer name.

import { COUNTRY_PORTRAITS } from './countryPortraits.generated';
import type { CompanyType } from './types';

/** Base public path every returned image URL is rooted at. */
export const PEOPLE_ASSETS_BASE = '/assets/people';

/**
 * The eight COMPANY TYPES a case is filed under: `data-companies` on the site,
 * `CompanyType` in `types.ts`. An alias rather than a second literal union of
 * the same eight ids, which is what used to stand here - two copies of one
 * vocabulary with nothing comparing them.
 *
 * The name is historical, and the sentence it used to carry was wrong in the
 * way that costs something. It read "`data-roles` on the site", which was true
 * only until the site split the two axes apart. Measured on the shipped
 * gallery, across all 202 cards: `data-companies` holds these eight ids and
 * `data-roles` holds the fifteen PROFESSION ids from `roles.ts`.
 *
 * That matters here because `ROLE_CAST` below is keyed by THESE ids. Look a
 * profession up in it and fourteen of the fifteen miss - and the fifteenth,
 * `project-manager`, belongs to both vocabularies and quietly returns a
 * portrait. A miss is visible; that one hit is not, which is why the parameter
 * types below name `CompanyType` instead of `string`.
 */
export type CaseRole = CompanyType;

/**
 * The cast of portrait stems for each case role, copied verbatim from the
 * marketing site's `put_case_face.py` ROLE_CAST so both surfaces agree on
 * who holds a role. The first entry is the archetype; a role is a small
 * cast rather than one person so a role with many cases does not repeat
 * the same face on neighbouring cards.
 */
export const ROLE_CAST: Record<CaseRole, string[]> = {
  'general-contractor': [
    'prf-general-contractor', 'prf-site-supervisor', 'prf-construction-manager',
    'prf-commercial-manager', 'prf-quality-manager', 'prf-hse-manager',
    'prf-scheduler-planner', 'prf-procurement-manager',
  ],
  'subcontractor': ['prf-subcontractor', 'prf-mep-contractor', 'prf-fitout-interiors'],
  'cost-consultant': ['prf-estimator', 'prf-commercial-manager', 'prf-procurement-manager'],
  'designer': ['prf-architecture-engineering', 'prf-design-build', 'prf-mep-contractor'],
  'developer-client': ['prf-real-estate-developer', 'prf-owner-client', 'prf-homebuilder'],
  'project-manager': ['prf-construction-manager', 'prf-scheduler-planner'],
  'bim-consultant': ['prf-bim-vdc', 'prf-architecture-engineering', 'prf-sustainability-esg'],
  'owner-operator': ['prf-facility-manager', 'prf-owner-client', 'prf-government-agency'],
};

/**
 * Case slug -> bespoke photo path for the ten flagship cases that were shot
 * individually (`pbk-<case-slug>.webp` maps 1:1 to the case slug). A bespoke
 * photo always wins over the pooled role cast in `caseFaceFor`.
 *
 * The takeoff shot was framed for the retired PDF pricing case; the German
 * takeoff case inherited that route, so it inherits the photograph, filed
 * under its own slug to keep the 1:1 rule. The retired case's own
 * `pbk-price-from-pdf.webp` is still on disk and is reached from nowhere -
 * eleven files against these ten entries. Deleting a shipped asset is the one
 * irreversible step here and has not been taken; `caseFaces.test.ts` names it
 * as retired so that the NEXT orphan fails instead of joining it quietly.
 */
export const BESPOKE_CASE_PHOTOS: Record<string, string> = {
  'answer-an-rfi': `${PEOPLE_ASSETS_BASE}/pbk-answer-an-rfi.webp`,
  'carbon-from-bim-6d': `${PEOPLE_ASSETS_BASE}/pbk-carbon-from-bim-6d.webp`,
  'change-to-paid-variation': `${PEOPLE_ASSETS_BASE}/pbk-change-to-paid-variation.webp`,
  'coordinate-and-resolve-model-clashes': `${PEOPLE_ASSETS_BASE}/pbk-coordinate-and-resolve-model-clashes.webp`,
  'handover-and-closeout': `${PEOPLE_ASSETS_BASE}/pbk-handover-and-closeout.webp`,
  'inspect-and-close-ncr': `${PEOPLE_ASSETS_BASE}/pbk-inspect-and-close-ncr.webp`,
  'project-end-to-end': `${PEOPLE_ASSETS_BASE}/pbk-project-end-to-end.webp`,
  'run-the-site-day': `${PEOPLE_ASSETS_BASE}/pbk-run-the-site-day.webp`,
  'takeoff-quantities-from-a-pdf-plan': `${PEOPLE_ASSETS_BASE}/pbk-takeoff-quantities-from-a-pdf-plan.webp`,
  'tender-from-boq': `${PEOPLE_ASSETS_BASE}/pbk-tender-from-boq.webp`,
};

/** The 24 company stems that exist on disk, each as a `cmp-*` scene and a
 *  `cmt-*` crop of that same scene. `companyThumbFor` and `companySceneFor`
 *  refuse to mint a path outside this set, so a renamed webp fails closed
 *  (null) instead of returning a 404 URL. */
const COMPANY_STEMS = new Set([
  'architecture-engineering', 'bim-vdc', 'civil-infrastructure', 'commercial-manager',
  'construction-manager', 'design-build', 'estimator', 'facility-manager',
  'fitout-interiors', 'full-enterprise', 'general-contractor', 'government-agency',
  'homebuilder', 'hse-manager', 'mep-contractor', 'modular-offsite',
  'owner-client', 'procurement-manager', 'quality-manager', 'real-estate-developer',
  'scheduler-planner', 'site-supervisor', 'subcontractor', 'sustainability-esg',
]);

/** Company-type ids (features/cases/companyTypes.ts) whose name differs from
 *  the photo stem. The alias points each company type at its archetype's photo
 *  - the same person `ROLE_CAST` lists first for it. Ids that already equal a
 *  stem (e.g. `general-contractor`) need no entry. */
const COMPANY_THUMB_ALIASES: Record<string, string> = {
  'cost-consultant': 'estimator',
  'designer': 'architecture-engineering',
  'developer-client': 'real-estate-developer',
  'project-manager': 'construction-manager',
  'bim-consultant': 'bim-vdc',
  'owner-operator': 'facility-manager',
};

/** Positive modulo, so a caller passing a negative index still lands inside
 *  the cast instead of producing `cast[-1]` (undefined). */
function mod(n: number, m: number): number {
  return ((n % m) + m) % m;
}

/** The prefix a pooled portrait path starts with. Country variants are minted
 *  by inserting the country code straight after it, so the stem is never
 *  parsed and a stem beginning with two letters can never be mistaken for a
 *  country code. */
const POOLED_PORTRAIT_PREFIX = `${PEOPLE_ASSETS_BASE}/prf-`;

/**
 * The country-specific portrait for a pooled one, or the pooled one unchanged.
 *
 * `prf-commercial-manager.webp` + `DE` -> `prf-de-commercial-manager.webp`,
 * but only when that file is in `available`. Returns the input untouched for a
 * case with no region, for a region that is not an ISO 3166-1 alpha-2 code,
 * for a bespoke `pbk-*` photo, and for a market whose art has not been shot -
 * the four cases where there is nothing national to prefer.
 *
 * The last of those is the one that decides how much this feature costs. The
 * name is minted either way; asking for it is what the manifest gates.
 *
 * @param pooled A path returned by the pooled casting.
 * @param region `Playbook.region`, e.g. "DE". Case-insensitive; the filename
 *   is always lowercase.
 * @param available The country portraits on disk, as bare filenames.
 */
function countryPortraitFor(pooled: string, region: string | undefined, available: ReadonlySet<string>): string {
  if (!region) return pooled;
  const code = region.trim().toLowerCase();
  if (!/^[a-z]{2}$/.test(code)) return pooled;
  if (!pooled.startsWith(POOLED_PORTRAIT_PREFIX)) return pooled;
  const stem = pooled.slice(POOLED_PORTRAIT_PREFIX.length);
  return available.has(`prf-${code}-${stem}`) ? `${POOLED_PORTRAIT_PREFIX}${code}-${stem}` : pooled;
}

/**
 * The photograph for one case: what to request, and what to show when the
 * request fails.
 *
 * Two fields rather than one string because the two answer different
 * questions. `src` is what to ask for, and it moves as country art arrives;
 * `pooled` is what this case wore before any market had a photograph, and it
 * is what a load failure lands on. Both are on disk - `caseFaces.test.ts`
 * proves it for every case in the catalogue, `src` included, now that the
 * manifest decides. Recovering one from the other by parsing was the
 * alternative and is worse: it would bake "a country code is two lowercase
 * letters" into a second place, and leave the closed-set test asserting on a
 * string it had to take apart first.
 */
export interface CaseFace {
  /** The portrait to request: the country variant when the case names a
   *  market that has been photographed, and the pooled portrait otherwise. */
  src: string;
  /** The pooled portrait. Always on disk; what `src` falls back to at load
   *  time (see `CaseFacePhoto`). Equal to `src` when there is no variant. */
  pooled: string;
}

/**
 * The photo for a case, matching the marketing site's `deal()` exactly.
 *
 * A bespoke `pbk-*` photo wins when the case slug has one. Otherwise the
 * first company type that has a cast wins (the site keys on the first
 * `data-companies` token), and the case gets `cast[indexInRole % cast.length]`
 * - a positional round-robin, so consecutive cases under one company type wear
 * consecutive faces and no two gallery neighbours repeat.
 *
 * The parameter is `CompanyType[]` and not `string[]` on purpose. It is a list
 * of COMPANY TYPES, never the professional roles in `Playbook.roles`; handing
 * it the latter used to typecheck and then return a portrait for the one id
 * the two vocabularies share. It is now a compile error instead.
 *
 * `region` is the LAST word, not the first: it decorates the stem the two
 * lines above already settled on. Country is a different axis from company
 * type and must not overrule it, so a market with art for some company types
 * and none for others falls back one pairing at a time rather than all or
 * nothing - the manifest is consulted per FILENAME, so the German estimator
 * whose photograph exists is used and the German scheduler whose photograph
 * does not stays pooled. There is no country parameter on the entry point
 * that returns a bare string, because there is no such entry point any more:
 * a surface that called one would show a country-blind face and nothing would
 * say so.
 *
 * @param caseId Case slug (e.g. `tender-from-boq`).
 * @param companyTypes The case's company types, primary first.
 * @param indexInRole Zero-based position of this case among the cases filed
 *   under its primary company type, in display order.
 * @param region The case's market (`Playbook.region`, ISO 3166-1 alpha-2), or
 *   undefined for a universal case.
 * @param available The country portraits on disk. Defaults to the generated
 *   manifest, which is what every caller in the app wants. It is a parameter
 *   at all because the shipped manifest is empty until the first webp is
 *   bought, and a branch no test can reach is a branch that will be broken by
 *   the change that finally reaches it - the tests hand it a market that has
 *   art so the country half is exercised before any exists.
 * @returns The requested path and its pooled fallback, or null when no company
 *   type in `companyTypes` has a cast.
 */
export function caseFaceFor(
  caseId: string,
  companyTypes: readonly CompanyType[],
  indexInRole: number,
  region?: string,
  available: ReadonlySet<string> = COUNTRY_PORTRAITS,
): CaseFace | null {
  const bespoke = BESPOKE_CASE_PHOTOS[caseId];
  if (bespoke) return { src: bespoke, pooled: bespoke };
  for (const companyType of companyTypes) {
    const cast = ROLE_CAST[companyType];
    if (cast && cast.length > 0) {
      const pooled = `${PEOPLE_ASSETS_BASE}/${cast[mod(indexInRole, cast.length)]}.webp`;
      return { src: countryPortraitFor(pooled, region, available), pooled };
    }
  }
  return null;
}

/**
 * The photo stem for a company type, total over BOTH id schemes:
 *
 *  - hyphenated case-role ids from `COMPANY_TYPE_META`
 *    (e.g. `general-contractor`, `cost-consultant`), and
 *  - underscored backend onboarding preset keys served by
 *    `GET /v1/users/onboarding-presets/`
 *    (e.g. `general_contractor`, `full_enterprise`).
 *
 * Underscores are normalised to hyphens, role ids that do not name a photo
 * stem go through `COMPANY_THUMB_ALIASES`, and a stem is only returned when
 * it is one of the 24 that exist on disk.
 */
function companyStemFor(companyTypeId: string): string | null {
  const normalized = companyTypeId.replace(/_/g, '-');
  const stem = COMPANY_THUMB_ALIASES[normalized] ?? normalized;
  return COMPANY_STEMS.has(stem) ? stem : null;
}

/**
 * The 128x128 square thumb for a company type, for the small tiles in the
 * "My company" selector and the onboarding profile cards. Accepts either id
 * scheme (see {@link companyStemFor}).
 *
 * @param companyTypeId A company-type id in either scheme.
 * @returns `/assets/people/cmt-<stem>.webp`, or null for an unknown id.
 */
export function companyThumbFor(companyTypeId: string): string | null {
  const stem = companyStemFor(companyTypeId);
  return stem ? `${PEOPLE_ASSETS_BASE}/cmt-${stem}.webp` : null;
}

/**
 * The full 340x480 company scene a `cmt-*` thumb is cropped from - the site
 * this kind of firm works on, not a person. For surfaces with room for the
 * whole picture; anything at tile size wants {@link companyThumbFor}.
 * Accepts either id scheme (see {@link companyStemFor}).
 *
 * @param companyTypeId A company-type id in either scheme.
 * @returns `/assets/people/cmp-<stem>.webp`, or null for an unknown id.
 */
export function companySceneFor(companyTypeId: string): string | null {
  const stem = companyStemFor(companyTypeId);
  return stem ? `${PEOPLE_ASSETS_BASE}/cmp-${stem}.webp` : null;
}

/** The little a case has to say about itself to be dealt a face. */
export interface CaseFaceInput {
  /** Case slug, the key the returned map is addressed by. */
  id: string;
  /** The case's company types, primary first (`Playbook.companyTypes`).
   *  Typed to the company vocabulary, not `string[]`, so `Playbook.roles`
   *  cannot be passed here by a caller who reads the two as interchangeable. */
  companyTypes: readonly CompanyType[];
  /** The market the case is authored for (`Playbook.region`, ISO 3166-1
   *  alpha-2 in upper case), or undefined for a universal case. Optional so a
   *  `Playbook` still satisfies this structurally with nothing to wire: all
   *  three callers already hand whole playbooks over, which is why the country
   *  axis arrives on every surface at once. */
  region?: string;
}

/**
 * Deal a face to every case in one pass, the way the site's `deal()` does.
 *
 * Position, not a hash of the slug: a hash spreads unevenly and collides,
 * while position guarantees that consecutive cases under one role get
 * consecutive people, so no two neighbours in the grid wear the same face.
 * A case with a bespoke photo still takes its turn in the round-robin, so
 * adding or removing one does not re-cast every case after it.
 *
 * Deal over the WHOLE catalogue rather than the filtered or windowed list.
 * The position a face is chosen by is a property of the case, and narrowing
 * the grid must not hand a case a different face than the one it wore before
 * the filter was clicked.
 *
 * Same casting logic as the marketing site, not necessarily the same person
 * on the same case: the site deals over its own gallery order, and the two
 * catalogues are neither the same length nor in the same order.
 *
 * The round-robin counter is kept per COMPANY TYPE and not per country. A
 * German and a Chinese case filed under the same company type therefore land
 * on different stems, so the two markets are not asked for the same portrait
 * twice over, and - the reason it matters more - a market whose art is only
 * half bought does not put every one of its cases on the one stem that
 * happens to exist.
 *
 * The manifest does not touch the counter. A market with half its art bought
 * deals exactly the same stems it dealt before the art arrived - the country
 * only decides whether the stem is asked for in its national cut - so buying
 * one photograph never re-casts the cases around it.
 *
 * @param cases The full case catalogue, in display order.
 * @param available The country portraits on disk; see {@link caseFaceFor}.
 * @returns Case slug -> requested path plus pooled fallback, holding only the
 *   cases that have a face.
 */
export function dealCaseFaces(
  cases: readonly CaseFaceInput[],
  available: ReadonlySet<string> = COUNTRY_PORTRAITS,
): Map<string, CaseFace> {
  const dealt = new Map<string, number>();
  const faces = new Map<string, CaseFace>();
  for (const c of cases) {
    // The company type that gets the counter is the one `caseFaceFor` will
    // cast from, so the position it counts is a position in that type's cast.
    const companyType = c.companyTypes.find((id) => ROLE_CAST[id]?.length);
    if (!companyType) continue;
    const index = dealt.get(companyType) ?? 0;
    dealt.set(companyType, index + 1);
    const face = caseFaceFor(c.id, [companyType], index, c.region, available);
    if (face) faces.set(c.id, face);
  }
  return faces;
}
