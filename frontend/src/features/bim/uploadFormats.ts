// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One list of what the BIM Hub upload accepts, and what happens to each format.
 *
 * This screen used to carry seven hand-maintained lists - two badge rows, two
 * size hints, two aria-labels and a rejection toast - and no two of them named
 * the same set. A user reported that alternative 3D formats such as .dae and
 * .3ds were "no longer visible"; nothing had been removed, the badge row simply
 * showed six of the fifteen accepted extensions behind a "+ more" chip that was
 * a plain span with nothing behind it. A capability the user cannot find is
 * indistinguishable from one we deleted.
 *
 * So the extensions live here once and every consumer derives from them: the
 * ``accept`` attributes, the badge rows, and the format names interpolated into
 * the translated strings. Extensions are not translatable, which is the point -
 * deriving the badges costs no locale work, while enumerating formats inside
 * prose is exactly how seven lists happened.
 *
 * The tier is carried alongside the extension because it is real information a
 * flat list would throw away: .ifc gives full properties and quantities, .stl
 * gives triangles, and .dwg is not imported here at all. The badge colour and
 * the explanatory note both read the tier rather than restating it.
 */

import { MESH_IMPORT_EXTENSIONS } from './meshImport/formats';

/**
 * What the upload does with a format.
 *
 * - ``bim``     native BIM, converted server-side with properties, quantities
 *               and classifications intact.
 * - ``mesh``    geometry only, parsed in-browser by the mesh importer. You can
 *               view and measure it; there is no BIM data to carry.
 * - ``handoff`` accepted by the picker, then routed to another module. Not a
 *               BIM Hub import at all, which is why it does not share the
 *               ``bim`` treatment even though the old badge row implied it did.
 */
export type UploadTier = 'bim' | 'mesh' | 'handoff';

export interface UploadFormat {
  readonly ext: string;
  readonly tier: UploadTier;
}

/** Native BIM models, converted server-side. Mirrors ``CAD_EXTENSIONS``. */
export const BIM_MODEL_EXTENSIONS = ['.rvt', '.ifc'] as const;

/** Drawings the picker takes and hands to DWG Takeoff. Mirrors ``DWG_EXTENSIONS``. */
export const HANDOFF_EXTENSIONS = ['.dwg', '.dxf'] as const;

/** Tabular element data, accepted only by the advanced mode's own input. */
export const DATA_EXTENSIONS = ['.csv', '.xlsx', '.xls'] as const;

/**
 * Every extension the single-file picker accepts, in the order it is shown.
 *
 * Mesh formats come from ``meshImport/formats``, which is also what
 * ``isMeshImportFile`` tests against, so the picker and the router that decides
 * where a picked file goes cannot disagree about which files are meshes.
 */
export const UPLOAD_FORMATS: readonly UploadFormat[] = [
  ...BIM_MODEL_EXTENSIONS.map((ext): UploadFormat => ({ ext, tier: 'bim' })),
  ...HANDOFF_EXTENSIONS.map((ext): UploadFormat => ({ ext, tier: 'handoff' })),
  ...MESH_IMPORT_EXTENSIONS.map((ext): UploadFormat => ({ ext, tier: 'mesh' })),
];

/** ``accept`` for the single-file picker: every format above. */
export const UPLOAD_ACCEPT = UPLOAD_FORMATS.map((f) => f.ext).join(',');

/** ``accept`` for the advanced mode's geometry slot: mesh formats only. */
export const MESH_ACCEPT = MESH_IMPORT_EXTENSIONS.join(',');

/** ``accept`` for the advanced mode's element-data slot: tabular only. */
export const DATA_ACCEPT = DATA_EXTENSIONS.join(',');

/**
 * Mesh formats the backend also stores raw, alongside a data file, in the
 * advanced two-slot mode. Anything else dropped in the geometry slot goes
 * through the in-browser mesh importer first and is posted as a normalized GLB.
 *
 * Written out rather than derived, because membership is decided by what the
 * server will store, which nothing about the extension itself tells you. It
 * lives here anyway so it is not the one list left somewhere else, and the
 * tests pin it as a subset of the mesh tier so it cannot come to name a format
 * the importer does not read.
 */
export const RAW_GEOMETRY_EXTENSIONS = ['.dae', '.glb', '.gltf'] as const;

/** The extensions in one tier, for a badge row or an interpolated string. */
export function extensionsInTier(tier: UploadTier): string[] {
  return UPLOAD_FORMATS.filter((f) => f.tier === tier).map((f) => f.ext);
}
