// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ODbL attribution gate for every surface that paints OpenStreetMap tiles.
//
// WHY THIS EXISTS. The dashboard map shipped with `attributionControl={false}`
// and nothing mounted in its place, so it drew OSM-derived tiles with zero
// credit on screen. OSM data is ODbL; the tiles rendered from it are a Produced
// Work, and a Produced Work owes attribution. (The share-alike obligation is on
// the database, not on the rendered image, so this gate asserts credit and
// nothing more.) The other three surfaces were already correct, which is the
// point: the defect was invisible precisely because it was one surface out of
// four, and no gate compared them.
//
// WHAT THIS ASSERTS, AND WHY IN THIS FORM.
//   1. Every named surface carries the OSM credit, either as the literal
//      copyright URL or by naming the shared constant that holds it. Rule 5
//      is what makes the indirection safe.
//   2. A surface that turns the built-in control OFF must mount one back. This
//      is the exact shape of the original defect.
//   3. Where a control is mounted, the credit must live on its
//      `customAttribution` prop, not merely somewhere in the file. Without this
//      an attribution moved into a dead comment would still pass rule 1.
//   4. No surface credits a provider whose tiles we no longer serve. This is
//      the second half of the CARTO defect: the tiles were replaced, and a
//      stale credit naming the old provider is a licence statement that is
//      simply false. Greps for the host, so a renamed constant cannot hide it.
//   5. The shared constants say what they must. The vector credit names OSM
//      AND the tile provider, because ODbL asks for the data credit and
//      courtesy asks for the host. The relief credit must NOT name OSM: those
//      tiles carry no OSM data at all, and crediting a source that is not in
//      the picture is its own kind of false statement. Rule 5 imports the two
//      constants; the surface rules above read source text, because what they
//      ask about is how a component is written and not what a value holds.
//
// WHY THE INDIRECTION. The credit used to be pasted literally into three
// components. That is what rules 1 and 3 were originally written against, and
// it is exactly the shape that lets a migration update two of three and leave
// the third crediting the wrong provider with every gate still green. The
// string now lives in one module and the components import it, so this gate
// follows the import instead of the literal.
//
// Rule 2 deliberately matches `<Attribution` with an optional suffix rather
// than the literal `<AttributionControl`. DashboardProjectsMap resolves the
// control off its dynamically-imported module (`mapLib?.AttributionControl`)
// and renders it as `<Attribution>`, so a gate written against the import name
// would be permanently red on correct code.
//
// The surfaces are enumerated by path, not globbed. A glob that matches
// nothing passes green, which is the same family of silent pass as
// `vitest run <path-that-does-not-exist>`; `readFileSync` on a named path
// throws instead. The first test below is the explicit guard against a
// vacuous pass. The list is a floor, not a census: a legitimate fifth map
// surface should be added here, but its absence must not be asserted, or
// this gate turns into a ratchet that breaks on new work.
//
// ONE SURFACE IS DELIBERATELY NOT IN THE LIST, and saying so is cheaper
// than letting the next reader wonder. `shared/ui/ProjectMap/streetThumbnail.ts`
// renders the vector style into an offscreen map and reads the canvas as a
// data URL. It draws no chrome at all, by design: a credit baked into a
// cached bitmap is text nobody can select, follow or hear read out, and it
// would double the one the consumer draws in the DOM. Adding it here would
// force it to name a credit constant it does not render, which is exactly
// the decorative mention rule 3 exists to reject. What it produces is
// credited where it is shown, on the project card, and rule 6 below is the
// assertion about that.
//
// Run: npx vitest run src/tests/everyMapSurfaceCreditsOpenStreetMap.test.ts

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import {
  RELIEF_ATTRIBUTION,
  TILE_ATTRIBUTION_HTML,
  TILE_ATTRIBUTION_TEXT,
} from '../shared/ui/ProjectMap/basemap';

const SRC = resolve(__dirname, '..');

/** The single module that owns every attribution string. */
const CREDIT_MODULE = 'shared/ui/ProjectMap/basemap.ts';

/** Every component that renders a basemap. */
const MAP_SURFACES = [
  'shared/ui/ProjectMap/ProjectMap.tsx',
  'features/dashboard/components/DashboardProjectsMap.tsx',
  'features/geo-hub/MapLibreViewer.tsx',
  'features/geo-hub/CesiumViewer.tsx',
] as const;

/** The credit link itself. */
const OSM_CREDIT = 'openstreetmap.org/copyright';

/**
 * The shared constants a surface may name instead of inlining the link.
 *
 * Two spellings of the same credit. `_HTML` is for anything that renders
 * markup, which is every MapLibre `AttributionControl`; `_TEXT` is the
 * same value with the tags taken out, derived from it at module load, for
 * a surface that shows the credit as text. The project card is the second
 * kind: it is a still image inside a card that navigates on click, where
 * an anchor either competes for the click or looks like a link and is not.
 *
 * Both are listed because rule 1 asks "does this file name the credit",
 * and a surface that legitimately uses only the text form would otherwise
 * be red on correct code.
 */
const VECTOR_CREDIT_CONSTS = ['TILE_ATTRIBUTION_HTML', 'TILE_ATTRIBUTION_TEXT'] as const;
const VECTOR_CREDIT_CONST = VECTOR_CREDIT_CONSTS[0];
const RELIEF_CREDIT_CONST = 'RELIEF_ATTRIBUTION';

/** True when the source names the vector credit in either spelling. */
function namesVectorCredit(text: string): boolean {
  return VECTOR_CREDIT_CONSTS.some((name) => text.includes(name));
}

/**
 * Providers we do not serve tiles from any more. Matched on the host, not on
 * a friendly name, because a host is what a licence statement points at and
 * it survives renaming.
 */
const RETIRED_PROVIDERS = ['cartocdn.com', 'carto.com'];

/** Turning the library's own control off. */
const DISABLES_BUILTIN = 'attributionControl={false}';

/** Mounting a control back: `<AttributionControl ...` or `<Attribution ...`. */
const MOUNTS_CONTROL = /<Attribution\w*[\s/>]/;

const sources = MAP_SURFACES.map((rel) => ({
  rel,
  text: readFileSync(resolve(SRC, rel), 'utf-8'),
}));

describe('every map surface credits OpenStreetMap', () => {
  it('actually read the files it claims to check', () => {
    // Without this, a rename that emptied the list would leave every
    // `it.each` below with nothing to iterate and the suite green.
    expect(sources).toHaveLength(MAP_SURFACES.length);
    expect(sources.length).toBeGreaterThanOrEqual(4);
    for (const { rel, text } of sources) {
      expect(text.length, `${rel} is empty`).toBeGreaterThan(1000);
    }
    const names = sources.map((s) => s.rel);
    expect(names).toContain('shared/ui/ProjectMap/ProjectMap.tsx');
    expect(names).toContain('features/dashboard/components/DashboardProjectsMap.tsx');
  });

  it.each(sources)('$rel shows the OpenStreetMap credit', ({ rel, text }) => {
    const credits = text.includes(OSM_CREDIT) || namesVectorCredit(text);
    expect(
      credits,
      `${rel} renders a basemap but neither carries the ${OSM_CREDIT} link nor ` +
        `imports one of ${VECTOR_CREDIT_CONSTS.join(' / ')}. Tiles rendered from ` +
        'OSM data are a Produced Work under ODbL and owe attribution.',
    ).toBe(true);
  });

  it.each(sources)('$rel replaces any control it switches off', ({ rel, text }) => {
    if (!text.includes(DISABLES_BUILTIN)) return;
    expect(
      MOUNTS_CONTROL.test(text),
      `${rel} sets ${DISABLES_BUILTIN} and never mounts an attribution ` +
        'control in its place, so the map draws with no credit at all.',
    ).toBe(true);
  });

  it.each(sources)('$rel puts the credit on the control, not in a comment', ({ rel, text }) => {
    const attributionProps = text
      .split('\n')
      .filter((line) => line.includes('customAttribution'));
    if (attributionProps.length === 0) return;
    for (const line of attributionProps) {
      expect(
        line.includes(OSM_CREDIT) || namesVectorCredit(line),
        `${rel} passes a customAttribution that does not credit OpenStreetMap: ${line.trim()}`,
      ).toBe(true);
    }
  });

  it.each(sources)('$rel does not credit a provider we dropped', ({ rel, text }) => {
    for (const host of RETIRED_PROVIDERS) {
      const offending = text
        .split('\n')
        .filter((line) => line.includes(host))
        .filter((line) => !line.trimStart().startsWith('//') && !line.trimStart().startsWith('*'));
      expect(
        offending,
        `${rel} still names ${host} outside a comment. We no longer serve its ` +
          'tiles, so any credit pointing there describes a picture nobody sees.',
      ).toEqual([]);
    }
  });

  // The two credits arrive by import, not by slicing them out of the module's
  // source. A value read through the module system is the constant it is named
  // after, whatever the file looks like on disk, and that is the whole point
  // here: this pair used to isolate each constant by searching for the next
  // `';\n'` after its declaration. Nothing forces LF on a .ts checkout and the
  // Windows runner takes the default, so on that machine the terminator is
  // `';\r\n'`, the search returned -1, and `slice(start, -1)` ran to the end of
  // the file. The relief assertion then read TILE_ATTRIBUTION_HTML, which
  // credits OpenStreetMap and is right to, and went red while saying nothing
  // about the relief credit. The vector assertion overran its constant too and
  // stayed green only because nothing is declared after it, which is the same
  // defect pointing the other way: an assertion about whichever constant is
  // last in the file, not about the one it names.
  //
  // The typeof guards are load-bearing rather than decorative. A constant that
  // was renamed away arrives as `undefined`, and `/openstreetmap/i.test`
  // stringifies that to "undefined" and answers false, so the relief rule
  // would pass on a module that no longer has a relief credit at all.
  it('the vector credit names both the data and the tile provider', () => {
    expect(
      typeof TILE_ATTRIBUTION_HTML,
      `${CREDIT_MODULE} does not export ${VECTOR_CREDIT_CONST}`,
    ).toBe('string');
    expect(TILE_ATTRIBUTION_HTML, 'the vector credit must link the OSM copyright page').toContain(
      OSM_CREDIT,
    );
    expect(
      /openfreemap|openmaptiles/i.test(TILE_ATTRIBUTION_HTML),
      'the vector credit must also name whoever serves the tiles, not just OSM',
    ).toBe(true);
    for (const host of RETIRED_PROVIDERS) {
      expect(TILE_ATTRIBUTION_HTML, `the vector credit still names ${host}`).not.toContain(host);
    }
  });

  it('the plain-text vector credit says the same thing without the markup', () => {
    expect(typeof TILE_ATTRIBUTION_TEXT, `${CREDIT_MODULE} does not export ${VECTOR_CREDIT_CONSTS[1]}`).toBe(
      'string',
    );
    // Derived from the value, not retyped and not sliced out of the module
    // source. Both alternatives are defects this file already carries the
    // scars of: the retyped credit is why the constant exists at all, and
    // the source slice is the CRLF bug described above.
    expect(TILE_ATTRIBUTION_TEXT).toContain('OpenStreetMap');
    expect(
      /openfreemap|openmaptiles/i.test(TILE_ATTRIBUTION_TEXT),
      'the text credit must also name whoever serves the tiles, not just OSM',
    ).toBe(true);
    expect(
      TILE_ATTRIBUTION_TEXT.includes('<'),
      'the text form still carries markup, so a surface rendering it as text ' +
        'would print tags at the reader',
    ).toBe(false);
    for (const host of RETIRED_PROVIDERS) {
      expect(TILE_ATTRIBUTION_TEXT, `the text credit still names ${host}`).not.toContain(host);
    }
  });

  it('the relief credit does not claim OpenStreetMap data', () => {
    expect(
      typeof RELIEF_ATTRIBUTION,
      `${CREDIT_MODULE} does not export ${RELIEF_CREDIT_CONST}`,
    ).toBe('string');
    expect(
      /openstreetmap/i.test(RELIEF_ATTRIBUTION),
      'the relief tiles carry no OSM data. Crediting OSM there is a false ' +
        'licence statement, the same defect as a stale credit, mirrored.',
    ).toBe(false);
    expect(RELIEF_ATTRIBUTION.toLowerCase()).toContain('natural earth');
  });

  // Rule 6. A surface that can show two different pictures needs both
  // credits, and needs them reachable from the same file.
  //
  // The project card is the only one. It normally shows a snapshot of the
  // vector style rendered offscreen, and it falls back to the relief tile
  // when that cannot be produced - no WebGL, a blocked style, a render
  // that misses its timeout. Those two pictures carry different data from
  // different sources under different licences, and one credit cannot be
  // right for both. Naming only one is not a formatting slip: the vector
  // half is an ODbL obligation and the relief half is a courtesy credit,
  // so getting it backwards is a false statement in one direction and a
  // breach in the other.
  //
  // Source text rather than behaviour, like rules 1 to 4, because what
  // this asks is how the component is written. WHICH credit is shown for
  // WHICH picture is a runtime question, and it is asserted in both
  // directions in
  // src/shared/ui/ProjectMap/__tests__/projectCardShowsStreetsOrSaysItIsTerrain.test.tsx.
  it('the project card names both credits, because it can show either picture', () => {
    const card = sources.find((s) => s.rel === 'shared/ui/ProjectMap/ProjectMap.tsx');
    expect(card, 'the card surface fell out of the list above').toBeDefined();
    const text = card!.text;
    expect(
      namesVectorCredit(text),
      'the card renders a vector snapshot and must name the vector credit',
    ).toBe(true);
    expect(
      text.includes(RELIEF_CREDIT_CONST),
      'the card falls back to the relief tile and must name the relief credit ' +
        'for it, or a fallback picture ships under an OpenStreetMap credit it ' +
        'has no OSM data to justify',
    ).toBe(true);
  });
});
