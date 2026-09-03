// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Gate for the case-photography plumbing. The one that matters most is the
// closed-set check at the bottom: every path the module can EVER return must
// name a file that exists under frontend/public/assets/people, so a renamed
// or deleted webp fails here instead of 404ing in production. Since the
// country manifest landed that check covers `src` as well as `pooled`, which
// is the whole of what the manifest bought.

import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  BESPOKE_CASE_PHOTOS,
  PEOPLE_ASSETS_BASE,
  ROLE_CAST,
  type CaseRole,
  caseFaceFor,
  companySceneFor,
  companyThumbFor,
  dealCaseFaces,
} from './caseFaces';
import { COUNTRY_PORTRAITS } from './countryPortraits.generated';
import { COMPANY_TYPE_META } from './companyTypes';
import { PLAYBOOKS } from './playbooks';

const HERE = dirname(fileURLToPath(import.meta.url));
const PEOPLE_DIR = resolve(HERE, '../../../public/assets/people');
const PRESETS_PY = resolve(HERE, '../../../../backend/app/core/onboarding_presets.py');

/** The closed set of files actually on disk. */
const filesOnDisk = new Set(readdirSync(PEOPLE_DIR));

/**
 * The country-portrait filename shape, mirroring COUNTRY_PORTRAIT_RE in
 * scripts/gen_case_country_portraits.py.
 *
 * Two copies of one rule, which normally is the thing to avoid - except that
 * the drift check below computes the expected manifest with THIS regex and
 * compares it to the manifest the script wrote with the other one. A
 * disagreement between the two produces different sets and fails there, which
 * is the only kind of copy worth keeping.
 */
const COUNTRY_PORTRAIT_RE = /^prf-[a-z]{2}-[a-z0-9-]+\.webp$/;

/**
 * A manifest that pretends every portrait in the cast has been shot for these
 * markets.
 *
 * The shipped manifest is empty - no country art has been bought yet - so
 * without this the country half of the module would be untestable, and a
 * branch no test can reach is the branch the first webp will break. Handing
 * the functions their manifest is what makes the feature provable before it
 * exists on disk.
 */
function shotFor(...regions: string[]): ReadonlySet<string> {
  const names = new Set<string>();
  for (const region of regions) {
    for (const cast of Object.values(ROLE_CAST)) {
      for (const stem of cast) names.add(`prf-${region}-${stem.slice('prf-'.length)}.webp`);
    }
  }
  return names;
}

/** Assert a public path returned by the module names a real file. */
function expectOnDisk(publicPath: string | null): void {
  expect(publicPath).not.toBeNull();
  expect(publicPath!.startsWith(`${PEOPLE_ASSETS_BASE}/`)).toBe(true);
  const file = publicPath!.slice(`${PEOPLE_ASSETS_BASE}/`.length);
  expect(filesOnDisk, `${file} is not in public/assets/people`).toContain(file);
}

/** The backend's company preset keys, read from the source of truth
 *  (COMPANY_PRESETS only - the SIZE_PRESETS dict below it is a different
 *  dimension and has no photos). */
function backendPresetKeys(): string[] {
  const text = readFileSync(PRESETS_PY, 'utf-8');
  const start = text.indexOf('COMPANY_PRESETS');
  const end = text.indexOf('SIZE_PRESETS');
  const section = text.slice(start, end === -1 ? undefined : end);
  const keys = [...section.matchAll(/key="([a-z0-9_]+)"/g)].map((m) => m[1]!);
  // The wizard shows at least the nine headline profiles; the catalogue has
  // grown past that. If this drops below nine the slice above went stale.
  expect(keys.length).toBeGreaterThanOrEqual(9);
  return keys;
}

describe('companyThumbFor', () => {
  it('resolves every COMPANY_TYPE_META id (hyphenated scheme) to a file on disk', () => {
    for (const meta of COMPANY_TYPE_META) {
      expectOnDisk(companyThumbFor(meta.id));
    }
  });

  it('resolves every backend onboarding preset key (underscored scheme) to a file on disk', () => {
    for (const key of backendPresetKeys()) {
      expectOnDisk(companyThumbFor(key));
    }
  });

  it('returns null for an unknown id instead of minting a 404 path', () => {
    expect(companyThumbFor('interior-decorator')).toBeNull();
    expect(companyThumbFor('')).toBeNull();
  });
});

describe('companySceneFor', () => {
  it('resolves every COMPANY_TYPE_META id (hyphenated scheme) to a file on disk', () => {
    for (const meta of COMPANY_TYPE_META) {
      expectOnDisk(companySceneFor(meta.id));
    }
  });

  it('resolves every backend onboarding preset key (underscored scheme) to a file on disk', () => {
    for (const key of backendPresetKeys()) {
      expectOnDisk(companySceneFor(key));
    }
  });

  it('returns null for an unknown id instead of minting a 404 path', () => {
    expect(companySceneFor('interior-decorator')).toBeNull();
    expect(companySceneFor('')).toBeNull();
  });

  it('names the same stem as the thumb it is cropped from', () => {
    for (const meta of COMPANY_TYPE_META) {
      const thumb = companyThumbFor(meta.id)!;
      expect(companySceneFor(meta.id)).toBe(thumb.replace('/cmt-', '/cmp-'));
    }
  });
});

/** A value that is NOT in the company vocabulary.
 *
 *  `caseFaceFor` and `CaseFaceInput` take `CompanyType` rather than `string`,
 *  so a caller can no longer wander into the unknown-id branch by accident -
 *  which is the point of the types. The branch still has to hold at runtime,
 *  because both id schemes arrive as plain strings from the server and from
 *  localStorage, so the only way left to test it is to force one through. The
 *  double assertion is deliberate and is the marker for "this is a negative
 *  control", not a shortcut around a type that was inconvenient. */
const NOT_A_COMPANY_TYPE = 'interior-decorator' as unknown as CaseRole;

describe('caseFaceFor', () => {
  const roles = Object.keys(ROLE_CAST) as CaseRole[];

  it('is deterministic - same inputs, same face', () => {
    for (const role of roles) {
      for (let i = 0; i < 5; i++) {
        expect(caseFaceFor('some-case', [role], i)).toEqual(caseFaceFor('some-case', [role], i));
      }
    }
  });

  it('never repeats a face on adjacent indices within a role whose cast has more than one member', () => {
    for (const role of roles) {
      const cast = ROLE_CAST[role];
      if (cast.length < 2) continue;
      for (let i = 0; i < cast.length * 2; i++) {
        const a = caseFaceFor('case-a', [role], i)?.src;
        const b = caseFaceFor('case-b', [role], i + 1)?.src;
        expect(a, `role ${role}, indices ${i}/${i + 1}`).not.toBe(b);
      }
    }
  });

  it('lets the first castable company type win, like the site keys on the first data-companies token', () => {
    expect(caseFaceFor('some-case', ['cost-consultant', 'general-contractor'], 0)?.src).toBe(
      `${PEOPLE_ASSETS_BASE}/prf-estimator.webp`,
    );
    expect(caseFaceFor('some-case', [NOT_A_COMPANY_TYPE, 'designer'], 0)?.src).toBe(
      `${PEOPLE_ASSETS_BASE}/prf-architecture-engineering.webp`,
    );
  });

  it('lets a bespoke pbk photo win over the pooled company cast', () => {
    for (const [slug, photo] of Object.entries(BESPOKE_CASE_PHOTOS)) {
      expect(caseFaceFor(slug, ['general-contractor'], 3)).toEqual({ src: photo, pooled: photo });
    }
  });

  it('returns null when no company type has a cast', () => {
    expect(caseFaceFor('some-case', [NOT_A_COMPANY_TYPE], 0)).toBeNull();
    expect(caseFaceFor('some-case', [], 0)).toBeNull();
  });
});

/**
 * The country axis. Which FILE the code asks for is decided here, against the
 * manifest of art that exists; what happens if the request fails anyway - a
 * deploy that lost the webp - is proved in caseFacePhoto.test.tsx.
 *
 * Most of these hand the functions a synthetic manifest through `shotFor`.
 * That is not a convenience: the shipped manifest is empty, so every one of
 * them would otherwise assert on the fallback and quietly stop testing the
 * country axis at all.
 */
describe('caseFaceFor - country variants', () => {
  it('asks for the country portrait when the market has been photographed', () => {
    const face = caseFaceFor('some-case', ['cost-consultant'], 0, 'DE', shotFor('de'));
    expect(face?.src).toBe(`${PEOPLE_ASSETS_BASE}/prf-de-estimator.webp`);
  });

  it('stays on the pooled portrait when the market has no art, rather than asking for nothing', () => {
    // The defect this manifest exists to close. Before it, the same call
    // returned prf-de-estimator.webp for a folder that has never held one, and
    // 61 tiles per render found that out by 404ing.
    const face = caseFaceFor('some-case', ['cost-consultant'], 0, 'DE', new Set<string>());
    expect(face?.src).toBe(`${PEOPLE_ASSETS_BASE}/prf-estimator.webp`);
    expect(face?.src).toBe(face?.pooled);
  });

  it('falls back one pairing at a time, so half-bought art does not cost a market its country face', () => {
    // One photograph bought, one not, in the same market. The estimator wears
    // it; the architect stays pooled. An all-or-nothing gate would have made
    // buying the first photograph do nothing.
    const half = new Set(['prf-de-estimator.webp']);
    expect(caseFaceFor('a', ['cost-consultant'], 0, 'DE', half)?.src).toBe(
      `${PEOPLE_ASSETS_BASE}/prf-de-estimator.webp`,
    );
    expect(caseFaceFor('b', ['designer'], 0, 'DE', half)?.src).toBe(
      `${PEOPLE_ASSETS_BASE}/prf-architecture-engineering.webp`,
    );
  });

  it('lowercases the market, because the asset folder is lowercase and Linux is not forgiving', () => {
    const cn = shotFor('cn');
    const upper = caseFaceFor('some-case', ['cost-consultant'], 0, 'CN', cn);
    const lower = caseFaceFor('some-case', ['cost-consultant'], 0, 'cn', cn);
    expect(upper?.src).toBe(`${PEOPLE_ASSETS_BASE}/prf-cn-estimator.webp`);
    expect(lower?.src).toBe(upper?.src);
  });

  it('keeps the pooled portrait beside the country one, so a market with no art has somewhere to land', () => {
    // The fallback for a market nobody has shot yet is not "some other
    // market's photo" and not "nothing" - it is the picture this case wore
    // before the country axis existed.
    const face = caseFaceFor('some-case', ['cost-consultant'], 0, 'ZZ');
    expect(face?.pooled).toBe(`${PEOPLE_ASSETS_BASE}/prf-estimator.webp`);
    expect(caseFaceFor('some-case', ['cost-consultant'], 0)?.pooled).toBe(face?.pooled);
  });

  it('leaves a universal case exactly where it was', () => {
    const before = `${PEOPLE_ASSETS_BASE}/prf-estimator.webp`;
    expect(caseFaceFor('some-case', ['cost-consultant'], 0)).toEqual({
      src: before,
      pooled: before,
    });
  });

  it('does not let the country overrule the company type', () => {
    // Country is a SECOND axis, not a replacement for the first. One market
    // asking two company types for a portrait must still get two different
    // people, or the German cases all end up wearing one face.
    const de = shotFor('de');
    const consultant = caseFaceFor('a', ['cost-consultant'], 0, 'DE', de)?.src;
    const designer = caseFaceFor('b', ['designer'], 0, 'DE', de)?.src;
    expect(consultant).toBe(`${PEOPLE_ASSETS_BASE}/prf-de-estimator.webp`);
    expect(designer).toBe(`${PEOPLE_ASSETS_BASE}/prf-de-architecture-engineering.webp`);
    expect(consultant).not.toBe(designer);
  });

  it('keeps the round-robin, so one market does not collapse onto one face', () => {
    // The thing a per-country cast would have destroyed. Thirteen German
    // general-contractor cases have to reach eight different Germans.
    //
    // The manifest is `shotFor('de')` and not the shipped one on purpose. With
    // an empty manifest all eight of these fall back to eight distinct POOLED
    // stems and the count below passes without a country name in sight - the
    // assertion would still be green and would have stopped meaning anything.
    const de = shotFor('de');
    const cast = ROLE_CAST['general-contractor'];
    const asked = cast.map((_, i) => caseFaceFor(`case-${i}`, ['general-contractor'], i, 'DE', de)?.src);
    expect(new Set(asked).size).toBe(cast.length);
    for (const src of asked) expect(src).toContain(`${PEOPLE_ASSETS_BASE}/prf-de-`);
  });

  it('leaves a bespoke photo country-blind, since a bespoke photo is already for one case', () => {
    const photo = BESPOKE_CASE_PHOTOS['takeoff-quantities-from-a-pdf-plan']!;
    // The one shipped case that is both bespoke and market-specific. The
    // manifest is a fully-shot German one, so this proves the bespoke branch
    // wins rather than proving that nothing was available anyway.
    expect(
      caseFaceFor('takeoff-quantities-from-a-pdf-plan', ['designer'], 0, 'DE', shotFor('de')),
    ).toEqual({ src: photo, pooled: photo });
  });

  it('ignores a region that is not an ISO 3166-1 alpha-2 code rather than minting a nonsense name', () => {
    // The manifest is seeded with the nonsense names themselves, so a build
    // that stopped validating the region would find its file and be caught
    // here. A manifest without them would let this pass on emptiness.
    const junk = new Set([
      'prf--estimator.webp',
      'prf-deu-estimator.webp',
      'prf-d-estimator.webp',
      'prf-de-de-estimator.webp',
      'prf-42-estimator.webp',
    ]);
    const pooled = `${PEOPLE_ASSETS_BASE}/prf-estimator.webp`;
    for (const bad of ['', 'DEU', 'd', 'de-DE', '42']) {
      expect(caseFaceFor('some-case', ['cost-consultant'], 0, bad, junk)?.src, bad).toBe(pooled);
    }
  });

  it('names a country file the pooled stem can be read straight out of', () => {
    // The convention is an INSERTION, not a rename: prf-<country>- then the
    // stem, unchanged. That is what lets the manifest be generated and what
    // keeps a stem whose own first segment is short from being ambiguous.
    const gb = shotFor('gb');
    for (const companyType of Object.keys(ROLE_CAST) as CaseRole[]) {
      const cast = ROLE_CAST[companyType];
      for (let i = 0; i < cast.length; i++) {
        const face = caseFaceFor('no-bespoke-case', [companyType], i, 'GB', gb)!;
        const stem = face.pooled.slice(`${PEOPLE_ASSETS_BASE}/prf-`.length);
        expect(face.src).toBe(`${PEOPLE_ASSETS_BASE}/prf-gb-${stem}`);
      }
    }
  });
});

describe('dealCaseFaces', () => {
  it('carries the case region through to the file it asks for', () => {
    const faces = dealCaseFaces(
      [
        { id: 'universal', companyTypes: ['designer'] },
        { id: 'german', companyTypes: ['designer'], region: 'DE' },
      ],
      shotFor('de'),
    );
    // Two cases, same company type, consecutive positions in the cast: the
    // country decorates whichever stem the round-robin reached, so the market
    // never re-casts the case.
    const cast = ROLE_CAST['designer'];
    expect(faces.get('universal')?.src).toBe(`${PEOPLE_ASSETS_BASE}/${cast[0]}.webp`);
    expect(faces.get('german')?.src).toBe(
      `${PEOPLE_ASSETS_BASE}/${cast[1]!.replace('prf-', 'prf-de-')}.webp`,
    );
    expect(faces.get('german')?.pooled).toBe(`${PEOPLE_ASSETS_BASE}/${cast[1]}.webp`);
  });

  it('deals the same stems whether or not the market has art, so buying a photo re-casts nobody', () => {
    // The counter is per company type and the manifest is consulted after it,
    // so the pooled half of every face is identical across the two runs. If
    // the manifest ever moved the round-robin, one purchase would shuffle
    // every case underneath it and the gallery would look re-dealt.
    const cases = [
      { id: 'a', companyTypes: ['general-contractor'] as const, region: 'DE' },
      { id: 'b', companyTypes: ['general-contractor'] as const },
      { id: 'c', companyTypes: ['general-contractor'] as const, region: 'GB' },
    ];
    const withArt = dealCaseFaces(cases, shotFor('de', 'gb'));
    const withNone = dealCaseFaces(cases, new Set<string>());
    for (const { id } of cases) {
      expect(withArt.get(id)?.pooled, id).toBe(withNone.get(id)?.pooled);
    }
    expect(withArt.get('a')?.src).toBe(`${PEOPLE_ASSETS_BASE}/prf-de-general-contractor.webp`);
    expect(withNone.get('a')?.src).toBe(`${PEOPLE_ASSETS_BASE}/prf-general-contractor.webp`);
  });


  it('deals each role round its cast by position, like the site', () => {
    const cast = ROLE_CAST['general-contractor'];
    const faces = dealCaseFaces(
      cast.map((_, i) => ({ id: `case-${i}`, companyTypes: ['general-contractor'] })),
    );
    cast.forEach((stem, i) => {
      expect(faces.get(`case-${i}`)?.src).toBe(`${PEOPLE_ASSETS_BASE}/${stem}.webp`);
    });
  });

  it('lets a bespoke case take its turn, so it does not re-cast the ones after it', () => {
    const cast = ROLE_CAST['general-contractor'];
    const faces = dealCaseFaces([
      { id: 'answer-an-rfi', companyTypes: ['general-contractor'] },
      { id: 'plain-case', companyTypes: ['general-contractor'] },
    ]);
    expect(faces.get('answer-an-rfi')?.src).toBe(BESPOKE_CASE_PHOTOS['answer-an-rfi']);
    expect(faces.get('plain-case')?.src).toBe(`${PEOPLE_ASSETS_BASE}/${cast[1]}.webp`);
  });

  it('counts each role on its own, so one role does not move another along', () => {
    const faces = dealCaseFaces([
      { id: 'a', companyTypes: ['general-contractor'] },
      { id: 'b', companyTypes: ['designer'] },
      { id: 'c', companyTypes: ['designer'] },
    ]);
    expect(faces.get('a')?.src).toBe(`${PEOPLE_ASSETS_BASE}/${ROLE_CAST['general-contractor'][0]}.webp`);
    expect(faces.get('b')?.src).toBe(`${PEOPLE_ASSETS_BASE}/${ROLE_CAST['designer'][0]}.webp`);
    expect(faces.get('c')?.src).toBe(`${PEOPLE_ASSETS_BASE}/${ROLE_CAST['designer'][1]}.webp`);
  });

  it('leaves out a case whose company types have no cast rather than guessing', () => {
    const faces = dealCaseFaces([
      { id: 'no-types', companyTypes: [] },
      { id: 'unknown-type', companyTypes: [NOT_A_COMPANY_TYPE] },
    ]);
    expect(faces.size).toBe(0);
  });
});

describe('closed set - every path the module can ever return exists on disk', () => {
  it('covers every pooled portrait reachable through caseFaceFor', () => {
    for (const companyType of Object.keys(ROLE_CAST) as CaseRole[]) {
      const cast = ROLE_CAST[companyType];
      for (let i = 0; i < cast.length; i++) {
        expectOnDisk(caseFaceFor('no-bespoke-case', [companyType], i)?.pooled ?? null);
      }
    }
  });

  it('covers every bespoke photo', () => {
    for (const [slug, photo] of Object.entries(BESPOKE_CASE_PHOTOS)) {
      expect(photo).toBe(`${PEOPLE_ASSETS_BASE}/pbk-${slug}.webp`);
      expectOnDisk(photo);
    }
  });

  /**
   * `pbk-*` files on disk that no case points at and that stay there on
   * purpose. Retiring a case retires its route, not its photograph: the
   * marketing site's `put_case_face.py` records that deleting a shipped asset
   * "earns its own decision" and declines to take it, so the file outlives the
   * case until somebody does.
   *
   * The list is what makes the check below a gate rather than a shrug. Without
   * a name to excuse, the disk half could only be written as "ignore whatever
   * is unexpected", which passes on everything; with it, this one file is
   * accounted for and the NEXT orphan fails.
   */
  const RETIRED_BESPOKE_PHOTOS = new Set(['pbk-price-from-pdf.webp']);

  it('has no bespoke photo on disk that nothing points at', () => {
    // The other direction of the check above. That one proves every entry
    // names a file; this one proves every file has an entry, so a photo left
    // behind by a rename, or shot for a case that never shipped, shows up here
    // instead of sitting in the folder unread. The country half has had both
    // directions since the manifest landed - this half had only one.
    const claimed = new Set(Object.keys(BESPOKE_CASE_PHOTOS).map((slug) => `pbk-${slug}.webp`));
    const orphans = [...filesOnDisk]
      .filter((name) => name.startsWith('pbk-'))
      .filter((name) => !claimed.has(name) && !RETIRED_BESPOKE_PHOTOS.has(name))
      .sort();
    expect(
      orphans,
      'pbk-*.webp on disk that no case claims - add the case, or retire the name in RETIRED_BESPOKE_PHOTOS',
    ).toEqual([]);
  });

  it('keeps the retired list honest, so a name cannot excuse a file that is gone', () => {
    // A retired entry whose file has since been deleted would sit here forever
    // excusing nothing, and would hide the day somebody finally takes the
    // delete decision. Both directions, same as the manifest.
    for (const name of RETIRED_BESPOKE_PHOTOS) {
      expect(filesOnDisk, `${name} is listed as retired but is not on disk`).toContain(name);
      const slug = name.slice('pbk-'.length, -'.webp'.length);
      expect(
        Object.keys(BESPOKE_CASE_PHOTOS),
        `${name} is listed as retired and also claimed by a case`,
      ).not.toContain(slug);
    }
  });

  it('covers every company thumb and scene reachable from either id scheme', () => {
    const ids = [...COMPANY_TYPE_META.map((m) => m.id as string), ...backendPresetKeys()];
    for (const id of ids) {
      expectOnDisk(companyThumbFor(id));
      expectOnDisk(companySceneFor(id));
    }
  });

  // The tests above feed hand-written role arrays, which can only prove the
  // module is consistent with itself. This one runs the real catalogue through
  // the same call the Cases hub makes, so a case shipping a company type
  // nobody cast - or a webp leaving the folder - fails here.
  // The check the whole feature turns on. Every path the real catalogue asks
  // for, `src` as well as `pooled`, has to name a file that is there - which
  // is only true because the manifest decides. Run against the version that
  // shipped without one it fails 61 times over, once per case that names a
  // market, and those 61 were 61 image requests answered with a 404 on every
  // render of the hub, the case page and the dashboard gallery.
  it('gives every shipped case a face that exists on disk, both halves', () => {
    const faces = dealCaseFaces(PLAYBOOKS);
    const missing = PLAYBOOKS.filter((pb) => !faces.has(pb.id)).map((pb) => pb.id);
    expect(missing, 'cases with no castable company type').toEqual([]);
    for (const [id, face] of faces) {
      expect(face.pooled, `${id} pooled`).toBeTruthy();
      expectOnDisk(face.pooled);
      expectOnDisk(face.src);
    }
  });

  // The counterpart, written so it survives the first webp landing. It says
  // what `src` must be for a case that names a market - the country file when
  // the manifest holds it, and the pooled photo when it does not - which is
  // true of today's empty manifest and stays true of a half-bought one. The
  // shape rule is asserted alongside, because that is what lets the founder
  // buy art by filename: prf-<lowercase country>- then the pooled stem,
  // unchanged.
  it('asks for the country file exactly when the market has been photographed', () => {
    const faces = dealCaseFaces(PLAYBOOKS);
    let regioned = 0;
    for (const pb of PLAYBOOKS) {
      const face = faces.get(pb.id)!;
      if (!pb.region || face.pooled.includes('/pbk-')) {
        expect(face.src, `${pb.id} has no market, so it asks for the pooled photo`).toBe(
          face.pooled,
        );
        continue;
      }
      regioned += 1;
      const stem = face.pooled.slice(`${PEOPLE_ASSETS_BASE}/prf-`.length);
      const wanted = `prf-${pb.region.toLowerCase()}-${stem}`;
      expect(face.src, pb.id).toBe(
        COUNTRY_PORTRAITS.has(wanted) ? `${PEOPLE_ASSETS_BASE}/${wanted}` : face.pooled,
      );
      // Lowercase, always. The pooled folder is entirely lowercase and a Linux
      // server is not as forgiving about it as the developer's filesystem.
      expect(wanted).toBe(wanted.toLowerCase());
    }
    // A floor, so this cannot be satisfied by a catalogue that lost its
    // market-specific cases: sixty-two of them carried a region when the
    // country axis was added, sixty-one of those with a pooled portrait
    // underneath rather than a bespoke photo.
    expect(regioned, 'cases carrying a region').toBeGreaterThan(50);
  });
});

/**
 * The manifest against the folder it was generated from.
 *
 * The manifest is the one thing in this feature that can be stale: it is
 * written by scripts/gen_case_country_portraits.py and committed, so a webp
 * dropped in without running the script, or removed while the manifest still
 * names it, puts the two out of step. Both directions fail here.
 */
describe('country portrait manifest', () => {
  /** The country portraits actually in the folder, read with this file's own
   *  copy of the shape rule rather than the script's. */
  const countryFilesOnDisk = new Set(
    [...filesOnDisk].filter((name) => COUNTRY_PORTRAIT_RE.test(name)),
  );

  it('reads the folder it claims to read', () => {
    // A positive control for everything below. With no country art bought, the
    // manifest and the disk scan are both empty and would agree even if
    // PEOPLE_DIR pointed at nothing - so first prove the same scan finds the
    // pooled portraits, and finds every stem the cast can reach.
    const pooledOnDisk = new Set(
      [...filesOnDisk].filter((name) => name.startsWith('prf-') && !COUNTRY_PORTRAIT_RE.test(name)),
    );
    expect(pooledOnDisk.size).toBeGreaterThanOrEqual(20);
    for (const cast of Object.values(ROLE_CAST)) {
      for (const stem of cast) expect(pooledOnDisk, stem).toContain(`${stem}.webp`);
    }
  });

  it('tells a country portrait from a pooled one', () => {
    // The regex itself, on names it will never see in one folder at once. A
    // scan that classified everything as pooled would sail through the check
    // above and then report an empty manifest for a full folder.
    expect(COUNTRY_PORTRAIT_RE.test('prf-de-estimator.webp')).toBe(true);
    expect(COUNTRY_PORTRAIT_RE.test('prf-cn-general-contractor.webp')).toBe(true);
    for (const notCountry of [
      'prf-estimator.webp',
      'prf-bim-vdc.webp',
      'prf-hse-manager.webp',
      'prf-mep-contractor.webp',
      'prf-deu-estimator.webp',
      'cmp-estimator.webp',
      'pbk-tender-from-boq.webp',
      'prf-DE-estimator.webp',
    ]) {
      expect(COUNTRY_PORTRAIT_RE.test(notCountry), notCountry).toBe(false);
    }
  });

  it('holds exactly the country portraits in public/assets/people', () => {
    // Set equality, both ways. A subset check passes when the manifest is
    // empty and the folder is not, which is the failure this exists to catch.
    const inManifestNotOnDisk = [...COUNTRY_PORTRAITS].filter((n) => !countryFilesOnDisk.has(n));
    const onDiskNotInManifest = [...countryFilesOnDisk].filter((n) => !COUNTRY_PORTRAITS.has(n));
    expect(
      onDiskNotInManifest,
      'country art was added without regenerating the manifest - run: python scripts/gen_case_country_portraits.py',
    ).toEqual([]);
    expect(
      inManifestNotOnDisk,
      'the manifest names country art that is not on disk - run: python scripts/gen_case_country_portraits.py',
    ).toEqual([]);
    expect([...COUNTRY_PORTRAITS].sort()).toEqual([...countryFilesOnDisk].sort());
  });

  it('cannot mistake a pooled portrait for a country one', () => {
    // The shape rule reads the two characters after `prf-` as a country code.
    // No stem in the cast starts with a two-letter segment today (`bim`, `hse`
    // and `mep` are three), but `prf-qs-consultant.webp` is a plausible next
    // hire and would be filed as country `qs` - swallowed by the manifest and
    // never dealt to anyone. This fails the day such a stem is added, which is
    // the day the convention needs rethinking rather than the day after.
    for (const cast of Object.values(ROLE_CAST)) {
      for (const stem of cast) {
        expect(COUNTRY_PORTRAIT_RE.test(`${stem}.webp`), stem).toBe(false);
      }
    }
    for (const name of countryFilesOnDisk) {
      const stem = name.slice('prf-XX-'.length, -'.webp'.length);
      expect(filesOnDisk, `${name} decorates a stem that is not on disk`).toContain(
        `prf-${stem}.webp`,
      );
    }
  });
});
