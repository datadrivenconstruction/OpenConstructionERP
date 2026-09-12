// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure matching logic behind the "Open from project files" picker.
 *
 * Every viewer/takeoff module (PDF takeoff, DWG takeoff, BIM viewer, point
 * cloud, CAD explorer) used to offer a local disk upload only, even when the
 * project's Files area already held the very drawing the user wanted. The
 * shared picker closes that gap; this module decides WHICH stored files a
 * given module may be offered.
 *
 * Two deliberate design rules, both learned from production bugs:
 *
 *  1. The filename is the PRIMARY signal, ``mime_type`` only a fallback.
 *     The CDE document model serialises the original filename as ``name``
 *     (NOT ``filename``), and ``mime_type`` is nullable and frequently wrong
 *     for CAD payloads, which servers happily label
 *     ``application/octet-stream``. So we parse the extension off ``name``
 *     and consult ``mime_type`` only when the name carries no extension at
 *     all. A file called ``plan.dwg`` is a DWG even if the server tagged it
 *     ``application/pdf``.
 *  2. A format that a module can only open AFTER DDC cad2data conversion is
 *     matched but flagged, never silently offered as instantly viewable.
 *     Callers surface the flag so the user knows a conversion step runs
 *     first. This is why the matcher returns a descriptor and not a boolean:
 *     a boolean would push the conversion rule into the component, where it
 *     could not be unit-tested.
 *
 * Nothing here imports React or the API layer, so it stays cheap to test.
 * It is not import-free, though: the human-readable label joins its formats
 * through the shared formatter so the separator follows the reader's
 * language, and that pulls in the preferences store. The matching itself is
 * still pure; only the label is localised.
 */

import { fmtList } from './formatters';

/** One format a calling module declares it can open. */
export interface AcceptedFormat {
  /** Lower-case extension INCLUDING the leading dot, e.g. ``'.dwg'``. */
  ext: string;
  /**
   * True when the module cannot render the file directly and the platform
   * must run it through the DDC cad2data conversion first (RVT/IFC in the
   * BIM viewer). The picker labels these so nothing is offered that would
   * simply fail to open.
   */
  needsConversion?: boolean;
  /**
   * True when picking the file hands it off to a DIFFERENT module rather
   * than opening it here (the BIM viewer routes DWG/DXF to DWG takeoff).
   * Kept explicit so the UI can say so instead of pretending to open it.
   */
  handoff?: boolean;
}

/** Outcome of matching one stored file against a module's accepted set. */
export interface ProjectFileMatch {
  /** The extension that matched, lower-case with the dot. */
  ext: string;
  /** Mirrors {@link AcceptedFormat.needsConversion} for the matched format. */
  needsConversion: boolean;
  /** Mirrors {@link AcceptedFormat.handoff} for the matched format. */
  handoff: boolean;
}

/**
 * The minimum shape the matcher needs. Declared structurally rather than
 * importing ``DocumentItem`` so this module stays free of API imports and
 * tests can pass plain object literals. ``DocumentItem`` satisfies it.
 */
export interface ProjectFileLike {
  name?: string | null;
  mime_type?: string | null;
  /**
   * Format the SERVER resolved for this row, without a leading dot (``'ifc'``).
   * Only the federated listing carries it; a plain ``DocumentItem`` does not,
   * which leaves every existing caller on the filename path unchanged.
   *
   * It matters for rows whose ``name`` is a title rather than a filename. A
   * converted BIM model is named by whoever imported it, so "Office tower"
   * carries no extension at all - and a row that matches nothing is dropped
   * silently, leaving a dialog that says the project holds no compatible file
   * while the module is displaying one. The server already knows the format
   * (it falls back to ``model_format``), so the last resort is to ask it
   * rather than to guess from a name that was never a filename.
   */
  extension?: string | null;
}

/**
 * Narrow MIME fallback, used ONLY for files stored without any extension in
 * their name. Intentionally small: a wrong guess here offers a file that
 * cannot be opened, which is worse than not offering it at all.
 */
const MIME_TO_EXT: Readonly<Record<string, string>> = {
  'application/pdf': '.pdf',
  'image/vnd.dwg': '.dwg',
  'application/acad': '.dwg',
  'image/vnd.dxf': '.dxf',
  'application/dxf': '.dxf',
  'model/gltf-binary': '.glb',
  'model/gltf+json': '.gltf',
  'model/obj': '.obj',
  'model/stl': '.stl',
  'application/vnd.ms-pki.stl': '.stl',
};

/**
 * Lower-case extension including the dot, or ``''`` when the name carries
 * none. Mirrors the existing idiom in ``features/bim/meshImport/formats.ts``
 * so both places agree on what "the extension" means.
 *
 * Uses ``lastIndexOf`` so a multi-dot name such as ``A-101.rev2.dwg``
 * resolves to ``.dwg`` and not ``.rev2.dwg``. A leading-dot name like
 * ``.gitignore`` is treated as having no extension, which is what a file
 * picker wants: it is a name, not a format.
 */
export function extensionOf(name: string | null | undefined): string {
  if (!name) return '';
  const dot = name.lastIndexOf('.');
  if (dot <= 0) return '';
  return name.slice(dot).toLowerCase();
}

/**
 * Match one stored project file against a module's accepted formats.
 * Returns a descriptor when the module can open the file, or ``null``.
 *
 * The filename wins whenever it carries an extension; ``mime_type`` and the
 * server-resolved ``extension`` are only consulted for extension-less names.
 * See the module docstring for why the name comes first, and
 * {@link ProjectFileLike.extension} for why the server's answer is the last
 * resort rather than an equal one.
 */
export function matchProjectFile(
  doc: ProjectFileLike,
  accepted: readonly AcceptedFormat[],
): ProjectFileMatch | null {
  let ext = extensionOf(doc.name);
  if (!ext) {
    // `split` always yields at least one element, but `noUncheckedIndexedAccess`
    // types the index access as possibly undefined, so guard it rather than
    // assert - the fallback is the same empty string the lookup below handles.
    const mime = (doc.mime_type ?? '').toLowerCase().split(';')[0]?.trim() ?? '';
    ext = MIME_TO_EXT[mime] ?? '';
  }
  if (!ext) {
    // Normalised the same way the accepted set spells it: lower case, one
    // leading dot. The server sends 'ifc'; a row that stored '.IFC' is the
    // same format and must not miss.
    const declared = (doc.extension ?? '').trim().toLowerCase().replace(/^\.+/, '');
    ext = declared ? `.${declared}` : '';
  }
  if (!ext) return null;
  const hit = accepted.find((a) => a.ext.toLowerCase() === ext);
  if (!hit) return null;
  return {
    ext,
    needsConversion: hit.needsConversion === true,
    handoff: hit.handoff === true,
  };
}

/** A stored file the calling module can open, plus how it will open it. */
export interface MatchedProjectFile<T extends ProjectFileLike> {
  doc: T;
  match: ProjectFileMatch;
}

/**
 * Filter a project's stored files down to the ones a module can open, with
 * an optional free-text search over the filename.
 *
 * Search is a case-insensitive substring over ``name`` only. Matching on the
 * id or the mime type would surface confusing hits (a user typing "pdf"
 * wants drawings named "pdf", not every PDF in the project - the list is
 * already filtered to openable formats).
 *
 * The input order is preserved so the caller controls sorting.
 */
export function filterProjectFiles<T extends ProjectFileLike>(
  docs: readonly T[] | null | undefined,
  accepted: readonly AcceptedFormat[],
  search = '',
): MatchedProjectFile<T>[] {
  if (!docs || docs.length === 0) return [];
  const q = search.trim().toLowerCase();
  const out: MatchedProjectFile<T>[] = [];
  for (const doc of docs) {
    const match = matchProjectFile(doc, accepted);
    if (!match) continue;
    if (q && !(doc.name ?? '').toLowerCase().includes(q)) continue;
    out.push({ doc, match });
  }
  return out;
}

/**
 * Human-readable format list for the picker's empty state, e.g.
 * ``"DWG, DXF"``. Derived from the accepted set so a module that changes
 * what it opens cannot drift out of sync with what the UI promises.
 */
export function acceptedFormatLabel(accepted: readonly AcceptedFormat[]): string {
  const seen = new Set<string>();
  const labels: string[] = [];
  for (const a of accepted) {
    const label = a.ext.replace(/^\./, '').toUpperCase();
    if (!label || seen.has(label)) continue;
    seen.add(label);
    labels.push(label);
  }
  return fmtList(labels);
}

/* ── Per-module accepted sets ──────────────────────────────────────────
 *
 * Each set is derived from what that module's loader ACTUALLY handles, not
 * from what sounds plausible. The source of truth is cited per set so a
 * future change to a loader has an obvious partner to update here.
 */

/** PDF takeoff. ``handleFileUpload`` feeds the bytes straight to
 *  ``pdfjsLib.getDocument``, so PDF and nothing else. */
export const PDF_TAKEOFF_FORMATS: readonly AcceptedFormat[] = [{ ext: '.pdf' }];

/** DWG takeoff. Source: the module's own upload inputs, which accept
 *  ``.dwg,.dxf``. Both are converted server-side via DDC cad2data before the
 *  canvas draws them, hence the conversion flag on each. */
export const DWG_TAKEOFF_FORMATS: readonly AcceptedFormat[] = [
  { ext: '.dwg', needsConversion: true },
  { ext: '.dxf', needsConversion: true },
];

/** Mesh formats the BIM viewer loads in-browser (three.js), geometry only.
 *  Source: ``features/bim/meshImport/formats.ts`` MESH_IMPORT_EXTENSIONS. */
const BIM_MESH_FORMATS: readonly AcceptedFormat[] = [
  '.obj',
  '.3ds',
  '.dae',
  '.fbx',
  '.lwo',
  '.stl',
  '.ply',
  '.gltf',
  '.glb',
  '.usd',
  '.usdz',
].map((ext) => ({ ext }));

/**
 * BIM viewer. Source: the upload input's accept list in ``BIMPage.tsx``
 * (``.rvt,.ifc,.dwg,.dxf`` + the mesh list).
 *
 * RVT and IFC are flagged ``needsConversion``: the platform never parses
 * them natively (no IfcOpenShell, no native IFC), they become viewable only
 * after the DDC cad2data pipeline produces canonical data. DWG/DXF are
 * flagged ``handoff`` because ``handleFileSelect`` deliberately routes them
 * to the DWG takeoff module rather than opening them as 3D models.
 */
export const BIM_VIEWER_FORMATS: readonly AcceptedFormat[] = [
  { ext: '.rvt', needsConversion: true },
  { ext: '.ifc', needsConversion: true },
  { ext: '.dwg', handoff: true },
  { ext: '.dxf', handoff: true },
  ...BIM_MESH_FORMATS,
];

/**
 * Design options. The picker offers two families:
 *
 *   1. CAD/BIM formats that the DDC cad2data pipeline can convert into a
 *      quantified model — every entry with ``needsConversion: true``.
 *   2. PDF/DWG drawings that serve as the design basis when the project
 *      is at a concept stage and no 3D model exists yet. A user attaches
 *      the drawing, describes the option in text, and may later replace it
 *      with a priced model. This is the common early-stage workflow
 *      (OC-07) and not offering it forced the user through a model-centric
 *      path they could not complete.
 */
export const DESIGN_OPTION_SOURCE_FORMATS: readonly AcceptedFormat[] = [
  // BIM/CAD — conversion-gated
  ...(['.rvt', '.ifc', '.dwg', '.dxf', '.dgn', '.rfa'] as const).map(
    (ext) => ({ ext, needsConversion: true }) as AcceptedFormat,
  ),
  // Drawings / plans — direct documents, no conversion needed
  { ext: '.pdf' },
];

/** Point cloud viewer. Source: ``features/pointcloud/api.ts``
 *  ACCEPTED_SCAN_FORMATS, which itself mirrors the backend module. */
export const POINTCLOUD_FORMATS: readonly AcceptedFormat[] = [
  { ext: '.las' },
  { ext: '.laz' },
  { ext: '.copc' },
  { ext: '.e57' },
];

/** CAD data explorer. Source: ``CAD_ACCEPT`` in ``CadDataExplorerPage.tsx``.
 *  Every one of these is tabular data extracted by DDC cad2data, so the
 *  whole set is conversion-gated. */
export const CAD_EXPLORER_FORMATS: readonly AcceptedFormat[] = [
  '.rvt',
  '.ifc',
  '.dwg',
  '.dgn',
  '.dxf',
  '.rfa',
].map((ext) => ({ ext, needsConversion: true }));
