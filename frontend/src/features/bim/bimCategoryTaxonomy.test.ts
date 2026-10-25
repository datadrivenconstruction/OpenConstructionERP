// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * #179 - the same IFC category was named two ways on one screen. The Filter
 * & Group panel on the left showed "Structural Foundation"; the Filtered
 * summary card on the right showed "StructuralFoundation", side by side with
 * the same count.
 *
 * There were two faults behind that, and both are pinned here.
 *
 *   1. The right panel printed `element_type` raw - it never called the
 *      helper at all. That is a call-site fault, covered by the source guard
 *      at the bottom of this file.
 *
 *   2. The helper itself disagreed with itself. "StructuralFoundation" only
 *      came out spaced because someone had typed `structuralfoundation` into
 *      the KNOWN_CATEGORIES table; "StructuralBeam", two rows above it in
 *      the same list, had no table entry and so came out unspaced. The
 *      curated table was carrying a job that belongs to a rule.
 *
 * The assertion that matters for (2) is not "StructuralBeam is spaced" on
 * its own - it is that the two arrive at a spaced label BY THE SAME ROUTE,
 * so adding a category to a model cannot reintroduce the split.
 *
 * Run:  npx vitest run src/features/bim/bimCategoryTaxonomy.test.ts
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { bucketOf, isHiddenByBuildingsOnly, isNoiseCategory, prettifyCategoryName } from './bimCategoryTaxonomy';

describe('"Building elements only" leaves out IFC voids (TC-GRP-04)', () => {
  it('treats openings and virtual elements as noise', () => {
    for (const cat of ['IfcOpeningElement', 'IfcOpeningStandardCase', 'IfcVirtualElement', 'IfcVoidingFeature']) {
      expect(isNoiseCategory(cat)).toBe(true);
    }
  });

  it('keeps doors, windows and walls as building elements', () => {
    for (const cat of ['IfcDoor', 'IfcWindow', 'IfcWall', 'IfcSlab', 'Doors', 'Windows']) {
      expect(isNoiseCategory(cat)).toBe(false);
    }
    expect(bucketOf('IfcDoor')).toBe('openings');
  });
});

describe('prettifyCategoryName - CamelCase categories (#179)', () => {
  it('spaces StructuralFoundation and StructuralBeam alike', () => {
    expect(prettifyCategoryName('StructuralFoundation')).toBe('Structural Foundation');
    expect(prettifyCategoryName('StructuralBeam')).toBe('Structural Beam');
  });

  it('does not need a curated table entry to do it', () => {
    // The bug was that only table-listed names were spaced. A category the
    // table has never heard of has to come out the same way, or the next
    // model with a new entity reopens the defect. None of these are in
    // KNOWN_CATEGORIES.
    expect(prettifyCategoryName('StructuralBeam')).toBe('Structural Beam');
    expect(prettifyCategoryName('PileCap')).toBe('Pile Cap');
    expect(prettifyCategoryName('CurtainPanel')).toBe('Curtain Panel');
    expect(prettifyCategoryName('RetainingWallFooting')).toBe('Retaining Wall Footing');
  });

  it('leaves an already-spaced name alone', () => {
    // Regression guard on the ordering: splitting a name that already has
    // spaces would put a second space in front of every word. Neither of
    // these is in KNOWN_CATEGORIES, so both really do reach the passthrough
    // branch rather than being answered by a table lookup.
    expect(prettifyCategoryName('Structural Foundation')).toBe('Structural Foundation');
    expect(prettifyCategoryName('Temporary Works Props')).toBe('Temporary Works Props');
    expect(prettifyCategoryName('Precast Stair Flight')).not.toMatch(/ {2}/);
  });

  it('still refuses to guess boundaries in an all-lowercase run', () => {
    // "Newcategory" carries no boundary to read. Inventing one gives
    // "New Cat Egory", which is worse than leaving it.
    expect(prettifyCategoryName('Newcategory')).toBe('Newcategory');
    expect(prettifyCategoryName('newcategory')).toBe('Newcategory');
  });

  it('keeps runs of capitals intact', () => {
    // An acronym has no lowercase-to-capital boundary inside it.
    expect(prettifyCategoryName('HVACZone')).toBe('HVACZone');
  });

  it('still handles the IFC entities and the curated table', () => {
    expect(prettifyCategoryName('IfcWall')).toBe('Wall');
    expect(prettifyCategoryName('IfcWallStandardCase')).toBe('Wall Standard Case');
    expect(prettifyCategoryName('Structuralcolumns')).toBe('Structural Columns');
    expect(prettifyCategoryName('Curtainwallmullions')).toBe('Curtain Wall Mullions');
    expect(prettifyCategoryName('None')).toBe('Uncategorised');
    expect(prettifyCategoryName('Walls')).toBe('Walls');
  });

  it('has something to say about absent input', () => {
    expect(prettifyCategoryName(null)).toBe('—');
    expect(prettifyCategoryName(undefined)).toBe('—');
    expect(prettifyCategoryName('   ')).toBe('—');
  });
});

/**
 * The call sites. BIMViewer mounts WebGL, so a jsdom render is a dead end
 * here - this reads the source instead. It pins that the summary panel and
 * the multi-select chip go through the helper rather than printing
 * `element_type` raw; it does not and cannot say what the panel looks like.
 */
describe('the summary panel names categories through the helper (#179)', () => {
  const VIEWER = readFileSync(
    resolve(__dirname, '..', '..', 'shared', 'ui', 'BIMViewer', 'BIMViewer.tsx'),
    'utf-8',
  );

  it('imports the same helper the Filter & Group panel uses', () => {
    expect(VIEWER).toContain("import { prettifyCategoryName } from '@/features/bim/bimCategoryTaxonomy'");
  });

  it('routes both category call sites through it', () => {
    // Counted per call site, not just "contains". Both sites used to spell
    // the call the same way, so a substring check for
    // "{prettifyCategoryName(cat)}" was satisfied by the summary chip's
    // template literal further up the file and one site could cover for the
    // other losing its call - which is how this guard passed a deliberately
    // reverted fix on the first attempt. The chip now reads its category off
    // a selection part, so the two spellings differ and each is counted on
    // its own: neither can stand in for the other.
    const breakdownRow = VIEWER.match(/prettifyCategoryName\(cat\)/g) ?? [];
    const summaryChip = VIEWER.match(/prettifyCategoryName\(part\.category\)/g) ?? [];
    expect(breakdownRow).toHaveLength(1);
    expect(summaryChip).toHaveLength(1);
  });

  it('does not print a raw element_type as a category label', () => {
    // The defect's exact shape: the breakdown row rendered `{cat}` bare.
    expect(VIEWER).not.toMatch(/>\{cat\}</);
  });

  it('routes the multi-select summary chip through it', () => {
    // "2 Walls, 1 Door" is built from the same element_type keys. The chip
    // builds one entry per part in selectionPartLabel, so that the count and
    // the list separator can be localised at render around a label that is
    // still English. Pin the helper being called as well as written: a
    // defined-but-unused selectionPartLabel would put the raw key back on
    // screen with the contains check above still green.
    expect(VIEWER).toContain('${prettifyCategoryName(part.category)}');
    expect(VIEWER).toContain('selectionParts.map(selectionPartLabel)');
  });
});

describe('isHiddenByBuildingsOnly', () => {
  it('hides Revit type definitions even in a building category', () => {
    expect(isHiddenByBuildingsOnly({ is_type_definition: true }, 'Structural Foundations')).toBe(true);
    expect(isHiddenByBuildingsOnly({ is_type_definition: false }, 'Structural Foundations')).toBe(false);
    expect(isHiddenByBuildingsOnly({}, 'Structural Foundations')).toBe(false);
  });
});
