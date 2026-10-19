// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Tests for the "Open from project files" matcher.
 *
 * Each case pins a rule that a plausible-looking implementation gets wrong,
 * and the docstring says WHY the case exists. The picker decides what a user
 * is allowed to open, so a false positive here means offering a file that
 * fails to load, and a false negative means the file the user came for is
 * invisible.
 */

import { describe, it, expect } from 'vitest';

import {
  acceptedFormatLabel,
  extensionOf,
  filterProjectFiles,
  matchProjectFile,
  BIM_VIEWER_FORMATS,
  CAD_EXPLORER_FORMATS,
  DESIGN_OPTION_SOURCE_FORMATS,
  DWG_TAKEOFF_FORMATS,
  PDF_TAKEOFF_FORMATS,
  POINTCLOUD_FORMATS,
  type ProjectFileLike,
} from './projectFileFormats';

/** Build a stored-file stub. ``name`` is the field the CDE document model
 *  really serialises; an earlier picker guessed ``filename`` and read
 *  undefined everywhere, so the fixtures use the real shape on purpose. */
function doc(name: string | null, mime: string | null = null): ProjectFileLike {
  return { name, mime_type: mime };
}

describe('extensionOf', () => {
  it('lower-cases the extension so an uppercase filename still matches', () => {
    /* Real drawing exports are frequently uppercase ("PLAN.PDF" straight off
     * a plotter). Comparing raw case would hide those files from the picker
     * entirely, which is the single most likely user-visible failure. */
    expect(extensionOf('PLAN.PDF')).toBe('.pdf');
    expect(extensionOf('Site-Model.IFC')).toBe('.ifc');
  });

  it('takes only the last segment of a name containing several dots', () => {
    /* Drawing registers name sheets like "A-101.rev2.dwg". Splitting on the
     * FIRST dot yields ".rev2.dwg" and the file never matches. */
    expect(extensionOf('A-101.rev2.dwg')).toBe('.dwg');
    expect(extensionOf('Tower.B.v3.final.pdf')).toBe('.pdf');
  });

  it('returns an empty string when the name carries no extension', () => {
    /* Files uploaded from some scanners and mobile clients have no extension
     * at all. The parser must yield "" rather than the whole filename,
     * otherwise every extension-less file matches whatever set it is
     * compared against. */
    expect(extensionOf('README')).toBe('');
    expect(extensionOf('drawing-no-ext')).toBe('');
  });

  it('treats a dotfile as having no extension', () => {
    /* ".gitignore" is a NAME, not a format. lastIndexOf would report
     * ".gitignore" as the extension without the `dot <= 0` guard. */
    expect(extensionOf('.gitignore')).toBe('');
  });

  it('survives a null or undefined name without throwing', () => {
    /* The picker crashed once on `name.toLowerCase()` when the API returned
     * a document without the field. The parser must guard, not assume. */
    expect(extensionOf(null)).toBe('');
    expect(extensionOf(undefined)).toBe('');
  });
});

describe('matchProjectFile', () => {
  it('matches an uppercase extension against the accepted set', () => {
    /* End-to-end version of the case-folding rule: an uppercase PDF must be
     * offered in the PDF takeoff module. */
    expect(matchProjectFile(doc('PLAN.PDF'), PDF_TAKEOFF_FORMATS)).toEqual({
      ext: '.pdf',
      needsConversion: false,
      handoff: false,
    });
  });

  it('rejects a file whose extension looks right but is not in the set', () => {
    /* A Revit family is a real CAD format and the CAD explorer does accept
     * it - but the PDF takeoff module cannot open it. Offering
     * it would hand the user a file that fails on load. */
    expect(matchProjectFile(doc('Bridge.rfa'), PDF_TAKEOFF_FORMATS)).toBeNull();
    expect(matchProjectFile(doc('Bridge.rfa'), DWG_TAKEOFF_FORMATS)).toBeNull();
    /* ...and the very same file IS offered where it genuinely opens. */
    expect(matchProjectFile(doc('Bridge.rfa'), CAD_EXPLORER_FORMATS)).not.toBeNull();
  });

  it('ignores a null mime_type and decides on the name alone', () => {
    /* mime_type is nullable on the document model. A null must not throw and
     * must not block a file whose name is unambiguous. */
    expect(matchProjectFile(doc('Level-02.dwg', null), DWG_TAKEOFF_FORMATS)).toEqual({
      ext: '.dwg',
      needsConversion: true,
      handoff: false,
    });
  });

  it('lets the filename win when mime_type disagrees with it', () => {
    /* Precedence rule. Servers mislabel CAD payloads constantly (usually as
     * application/octet-stream, sometimes as application/pdf). A file named
     * .dwg is a DWG: it must NOT appear in the PDF takeoff picker just
     * because the stored mime says PDF, and it MUST appear in the DWG one. */
    const mislabelled = doc('Level-02.dwg', 'application/pdf');
    expect(matchProjectFile(mislabelled, PDF_TAKEOFF_FORMATS)).toBeNull();
    expect(matchProjectFile(mislabelled, DWG_TAKEOFF_FORMATS)).not.toBeNull();
  });

  it('falls back to the server-resolved extension when the name is a title', () => {
    /* A converted BIM model is NAMED by whoever imported it, so "Office
     * tower" carries no extension and no useful mime. The federated listing
     * still knows the format (it falls back to model_format), and without
     * consulting it the row is dropped silently - leaving a dialog that says
     * the project holds no compatible file while the module is displaying
     * one. The listing also spells the format bare and sometimes upper-case,
     * hence the normalisation. */
    expect(
      matchProjectFile(
        { name: 'Office tower', mime_type: null, extension: 'ifc' },
        DESIGN_OPTION_SOURCE_FORMATS,
      ),
    ).toEqual({ ext: '.ifc', needsConversion: true, handoff: false });
    expect(
      matchProjectFile(
        { name: 'Office tower', mime_type: null, extension: '.RVT' },
        DESIGN_OPTION_SOURCE_FORMATS,
      ),
    ).toEqual({ ext: '.rvt', needsConversion: true, handoff: false });
  });

  it('lets the filename beat the server-resolved extension', () => {
    /* Same precedence rule as mime_type: the declared extension is the LAST
     * resort, never an equal vote. A row named .dwg whose stored format says
     * ifc is a DWG, and treating it as an IFC would offer a file the module
     * cannot turn into a model. */
    expect(
      matchProjectFile(
        { name: 'Level-02.dwg', mime_type: null, extension: 'ifc' },
        [{ ext: '.ifc' }],
      ),
    ).toBeNull();
  });

  it('ignores a blank server-resolved extension rather than matching on a dot', () => {
    /* The field is nullable and is often an empty string. Normalising '' into
     * '.' would make every accepted set that happens to contain a dotted
     * entry match a row with no format at all. */
    expect(
      matchProjectFile({ name: 'unknown', mime_type: null, extension: '' }, DESIGN_OPTION_SOURCE_FORMATS),
    ).toBeNull();
    expect(
      matchProjectFile({ name: 'unknown', mime_type: null, extension: null }, DESIGN_OPTION_SOURCE_FORMATS),
    ).toBeNull();
  });

  it('offers the design-option module only what it can turn into a model', () => {
    /* Meshes and spreadsheets never become a quantified model, so offering
     * them promises something the module cannot do. PDF drawings are valid
     * as a concept-stage design basis (OC-07) and are accepted. */
    expect(matchProjectFile(doc('Tower.ifc'), DESIGN_OPTION_SOURCE_FORMATS)).not.toBeNull();
    expect(matchProjectFile(doc('Tower.glb'), DESIGN_OPTION_SOURCE_FORMATS)).toBeNull();
    expect(matchProjectFile(doc('Quantities.xlsx'), DESIGN_OPTION_SOURCE_FORMATS)).toBeNull();
    expect(matchProjectFile(doc('Plan.pdf'), DESIGN_OPTION_SOURCE_FORMATS)).not.toBeNull();
  });

  it('falls back to mime_type only when the name has no extension', () => {
    /* The fallback is what rescues extension-less uploads, but it is a last
     * resort by design - see the previous test for the precedence. */
    expect(matchProjectFile(doc('scan-0417', 'application/pdf'), PDF_TAKEOFF_FORMATS)).toEqual({
      ext: '.pdf',
      needsConversion: false,
      handoff: false,
    });
    /* An extension-less file with no usable mime is simply not offered,
     * rather than being guessed into some module's list. */
    expect(matchProjectFile(doc('scan-0417', null), PDF_TAKEOFF_FORMATS)).toBeNull();
    expect(
      matchProjectFile(doc('scan-0417', 'application/octet-stream'), PDF_TAKEOFF_FORMATS),
    ).toBeNull();
  });

  it('normalises a mime type that carries parameters', () => {
    /* Some uploaders store 'application/pdf; charset=binary'. An exact-string
     * lookup would miss it and the file would silently disappear. */
    expect(
      matchProjectFile(doc('scan-0417', 'application/pdf; charset=binary'), PDF_TAKEOFF_FORMATS),
    ).not.toBeNull();
  });

  it('flags RVT and IFC in the BIM viewer as needing conversion', () => {
    /* Project rule: the platform never parses IFC or RVT natively, they are
     * viewable only after the DDC cad2data pipeline runs. The picker must be
     * able to say so instead of implying an instant open. */
    expect(matchProjectFile(doc('Tower.ifc'), BIM_VIEWER_FORMATS)?.needsConversion).toBe(true);
    expect(matchProjectFile(doc('Tower.rvt'), BIM_VIEWER_FORMATS)?.needsConversion).toBe(true);
  });

  it('does not flag an in-browser mesh format as needing conversion', () => {
    /* Counterpart to the previous test: glTF/OBJ/STL load directly in
     * three.js. Flagging everything would make the conversion notice
     * meaningless noise. */
    expect(matchProjectFile(doc('Facade.glb'), BIM_VIEWER_FORMATS)?.needsConversion).toBe(false);
    expect(matchProjectFile(doc('Facade.obj'), BIM_VIEWER_FORMATS)?.needsConversion).toBe(false);
  });

  it('flags DWG in the BIM viewer as a handoff to another module', () => {
    /* BIMPage.handleFileSelect deliberately forwards DWG/DXF to DWG takeoff
     * instead of opening them as 3D models. The picker must advertise the
     * handoff rather than claim the BIM viewer opens the file. */
    const m = matchProjectFile(doc('Level-02.dwg'), BIM_VIEWER_FORMATS);
    expect(m).toEqual({ ext: '.dwg', needsConversion: false, handoff: true });
  });

  it('offers point cloud containers only in the point cloud module', () => {
    /* Guards the module boundary in the other direction: a scan must not
     * leak into a drawing module's picker. */
    expect(matchProjectFile(doc('site.e57'), POINTCLOUD_FORMATS)).not.toBeNull();
    expect(matchProjectFile(doc('site.e57'), BIM_VIEWER_FORMATS)).toBeNull();
    expect(matchProjectFile(doc('site.laz'), POINTCLOUD_FORMATS)).not.toBeNull();
  });

  it('returns null for an empty accepted set instead of matching everything', () => {
    /* Defensive: a module that passes an empty list must show nothing, not
     * the whole project. */
    expect(matchProjectFile(doc('PLAN.PDF'), [])).toBeNull();
  });
});

describe('filterProjectFiles', () => {
  const files = [
    doc('A-101.rev2.dwg'),
    doc('PLAN.PDF'),
    doc('README'),
    doc('Tower.ifc'),
    doc('site.e57'),
    doc(null, 'application/pdf'),
  ];

  it('keeps only the files the calling module can open', () => {
    /* The core promise of the picker: a DWG module lists drawings, not the
     * project's whole document shelf. */
    const out = filterProjectFiles(files, DWG_TAKEOFF_FORMATS);
    expect(out.map((f) => f.doc.name)).toEqual(['A-101.rev2.dwg']);
  });

  it('applies the search box case-insensitively over the filename', () => {
    /* The search must find "plan.pdf" when the user types lower-case "plan"
     * even though the stored name is uppercase. */
    const out = filterProjectFiles(files, PDF_TAKEOFF_FORMATS, 'plan');
    expect(out.map((f) => f.doc.name)).toEqual(['PLAN.PDF']);
  });

  it('treats a whitespace-only search as no search at all', () => {
    /* Typing then deleting leaves a stray space; the list must come back
     * rather than going mysteriously empty. */
    expect(filterProjectFiles(files, PDF_TAKEOFF_FORMATS, '   ')).toHaveLength(2);
  });

  it('never crashes on a null name while searching', () => {
    /* Combines the two nastiest inputs: a document with no name at all, and
     * an active search term that must skip it instead of throwing. */
    expect(() => filterProjectFiles(files, PDF_TAKEOFF_FORMATS, 'plan')).not.toThrow();
    const out = filterProjectFiles(files, PDF_TAKEOFF_FORMATS, 'plan');
    expect(out.every((f) => typeof f.doc.name === 'string')).toBe(true);
  });

  it('returns an empty array for null, undefined or empty input', () => {
    /* React Query hands `undefined` while the documents request is in
     * flight. The picker renders its loading/empty state off this. */
    expect(filterProjectFiles(null, PDF_TAKEOFF_FORMATS)).toEqual([]);
    expect(filterProjectFiles(undefined, PDF_TAKEOFF_FORMATS)).toEqual([]);
    expect(filterProjectFiles([], PDF_TAKEOFF_FORMATS)).toEqual([]);
  });

  it('preserves the caller-supplied order', () => {
    /* Sorting is the page's decision (most-recent-first, by name, ...).
     * The filter must not silently reorder. */
    const out = filterProjectFiles(files, BIM_VIEWER_FORMATS);
    expect(out.map((f) => f.doc.name)).toEqual(['A-101.rev2.dwg', 'Tower.ifc']);
  });
});

describe('acceptedFormatLabel', () => {
  it('renders a de-duplicated, upper-case list for the empty state', () => {
    /* The empty state tells the user which formats WOULD show up here. It is
     * derived from the accepted set so it cannot drift from reality, and it
     * must not print "DWG, DWG" when two entries share an extension. */
    expect(acceptedFormatLabel(DWG_TAKEOFF_FORMATS)).toBe('DWG, DXF');
    expect(acceptedFormatLabel(POINTCLOUD_FORMATS)).toBe('LAS, LAZ, COPC, E57');
    expect(acceptedFormatLabel([{ ext: '.dwg' }, { ext: '.dwg' }])).toBe('DWG');
  });
});
