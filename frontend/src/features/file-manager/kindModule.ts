// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { BarChart3, Box, Eye, FileBarChart, FileText, Image as ImageIcon, MapPin, Package, Pencil, PenTool, PlayCircle, Radar, Ruler, type LucideIcon } from 'lucide-react';
import type { FileKind } from './types';

// Single source of truth for per-kind accent colours. Both the landing
// folder grid (FolderCardGrid) and the storage stats strip (FilesStatsStrip)
// consume this so every category shows exactly one accent colour everywhere
// on the same screen. `tile`/`icon`/`ring` style the folder-card icon chip;
// `bar` is the solid accent used for storage bars, dots and micro-bars.
export interface KindTone {
  tile: string;
  icon: string;
  ring: string;
  bar: string;
}

export const KIND_TONE: Record<FileKind, KindTone> = {
  document: {
    tile: 'bg-sky-50 dark:bg-sky-950/30',
    icon: 'text-sky-600 dark:text-sky-400',
    ring: 'group-hover:ring-sky-500/30',
    bar: 'bg-sky-500',
  },
  photo: {
    tile: 'bg-emerald-50 dark:bg-emerald-950/30',
    icon: 'text-emerald-600 dark:text-emerald-400',
    ring: 'group-hover:ring-emerald-500/30',
    bar: 'bg-emerald-500',
  },
  sheet: {
    tile: 'bg-amber-50 dark:bg-amber-950/30',
    icon: 'text-amber-600 dark:text-amber-400',
    ring: 'group-hover:ring-amber-500/30',
    bar: 'bg-amber-500',
  },
  bim_model: {
    tile: 'bg-violet-50 dark:bg-violet-950/30',
    icon: 'text-violet-600 dark:text-violet-400',
    ring: 'group-hover:ring-violet-500/30',
    bar: 'bg-violet-500',
  },
  dwg_drawing: {
    tile: 'bg-orange-50 dark:bg-orange-950/30',
    icon: 'text-orange-600 dark:text-orange-400',
    ring: 'group-hover:ring-orange-500/30',
    bar: 'bg-orange-500',
  },
  takeoff: {
    tile: 'bg-cyan-50 dark:bg-cyan-950/30',
    icon: 'text-cyan-600 dark:text-cyan-400',
    ring: 'group-hover:ring-cyan-500/30',
    bar: 'bg-cyan-500',
  },
  report: {
    tile: 'bg-pink-50 dark:bg-pink-950/30',
    icon: 'text-pink-600 dark:text-pink-400',
    ring: 'group-hover:ring-pink-500/30',
    bar: 'bg-pink-500',
  },
  markup: {
    tile: 'bg-rose-50 dark:bg-rose-950/30',
    icon: 'text-rose-600 dark:text-rose-400',
    ring: 'group-hover:ring-rose-500/30',
    bar: 'bg-rose-500',
  },
};

// Solid accent (the `bar` tone) keyed by kind — the storage-breakdown bar
// and legend dots use this so they match the folder-card accents exactly.
export const KIND_COLORS: Record<FileKind, string> = {
  document: KIND_TONE.document.bar,
  photo: KIND_TONE.photo.bar,
  sheet: KIND_TONE.sheet.bar,
  bim_model: KIND_TONE.bim_model.bar,
  dwg_drawing: KIND_TONE.dwg_drawing.bar,
  takeoff: KIND_TONE.takeoff.bar,
  report: KIND_TONE.report.bar,
  markup: KIND_TONE.markup.bar,
};

// All file kinds in canonical display order. The stable denominator for the
// "Categories" KPI (every project has these N kinds, even when empty).
export const ALL_KINDS: readonly FileKind[] = [
  'document',
  'photo',
  'sheet',
  'bim_model',
  'dwg_drawing',
  'takeoff',
  'report',
  'markup',
];

// One file kind can be opened in several modules — a single .pdf is
// either a project document, a takeoff source, or a tender attachment.
// The first entry in each list is the "primary" / suggested module.
//
// Each `route` builder receives the project id and (optionally) a file
// id. Where the receiving module supports a deep-link param, the file
// id is appended so clicking actually opens the right file inside the
// destination — not just the bare module shell.
export interface ModuleTarget {
  label: string;
  i18nKey: string;
  description: string;
  descriptionI18nKey: string;
  icon: LucideIcon;
  /** Path template — `{projectId}` is substituted in by the consumer.
   *  `extra` carries the FileRow's `extra` bag so kind-specific routes can
   *  read fields beyond the id (e.g. a sheet's parent `document_id`). */
  route: (projectId: string, fileId?: string, extra?: Record<string, unknown>) => string;
  /**
   * Some destinations (Clash Detection, CAD-BIM BI Explorer) resolve the
   * project from the global project-context store rather than from a path
   * param, so they'd land on the empty "no project" state when reached via
   * a deep-link. When this flag is set the consumer must call
   * `useProjectContextStore.setActiveProject(...)` for the file's project
   * BEFORE navigating so the destination opens populated.
   */
  setsActiveProject?: boolean;
  /**
   * When set, this target is NOT a route to another module - it just opens
   * the file in a focused inline viewer overlay (the shared
   * ``InlinePdfPreviewModal``) on the current screen. Consumers must check
   * this flag and open the modal instead of calling ``navigate(route(...))``.
   * The ``route`` still returns a sensible fallback (keep the file selected
   * in /files) so a consumer that hasn't been taught about the flag yet
   * degrades to a harmless navigation rather than a dead click.
   *
   * Why this exists (issue #284): a PDF in Project Files used to ALWAYS open
   * in PDF Takeoff, but most PDFs are contracts / specs / letters, not
   * takeoff plans. The default is now "just read it" inline; PDF Takeoff is
   * offered as an explicit, separate choice the user opts into.
   */
  inlinePreview?: boolean;
  /**
   * Like ``inlinePreview`` but for an image or video: the file opens in the
   * shared ``MediaLightbox`` overlay (an authed ``<img>`` for images, an
   * authed ``<video controls>`` for clips) on the current screen instead of
   * navigating to a module. Consumers must check this flag and open the
   * lightbox instead of calling ``navigate(route(...))``; the ``route`` is a
   * harmless fallback that keeps the file selected in /files.
   *
   * Why this exists (issue #284 follow-up, ITEM 10): image and video uploads
   * used to fall through to PDF Takeoff (the document kind's default module),
   * which cannot render them. They now open in a proper viewer/player.
   */
  mediaPreview?: boolean;
}

const PROJECT = (p: string, sub: string) => `/projects/${p}/${sub}`;

// Append a deep-link query parameter only when we actually have a file
// id. Keeping the bare path when it's missing avoids URLs like
// `/takeoff?doc=` that some routers parse as an empty string.
const withParam = (path: string, key: string, value?: string): string =>
  value ? `${path}${path.includes('?') ? '&' : '?'}${key}=${encodeURIComponent(value)}` : path;

export const KIND_MODULES: Record<FileKind, ModuleTarget[]> = {
  document: [
    // Primary: open the PDF in the takeoff viewer with the measurements
    // tab pre-selected. TakeoffPage hydrates the viewer from either its
    // own server documents OR the central documents module by id, so
    // either source resolves the file. `&source=document` tells the
    // viewer to fall back to the documents module's download URL.
    {
      label: 'PDF Takeoff',
      i18nKey: 'files.module.pdf_takeoff',
      description: 'Open this PDF and start measuring',
      descriptionI18nKey: 'files.module.pdf_takeoff_desc',
      icon: Ruler,
      route: (_p, f) =>
        f
          ? `/takeoff?doc=${encodeURIComponent(f)}&source=document&tab=measurements`
          : '/takeoff',
    },
    {
      label: 'File Manager',
      i18nKey: 'files.module.documents',
      description: 'Stay in /files with this document selected',
      descriptionI18nKey: 'files.module.documents_desc',
      icon: FileText,
      route: (p, f) => withParam(PROJECT(p, 'files'), 'file', f),
    },
  ],
  photo: [
    {
      label: 'Site Photos',
      i18nKey: 'files.module.photos',
      description: 'Browse geo-tagged site photography',
      descriptionI18nKey: 'files.module.photos_desc',
      icon: ImageIcon,
      route: (_p, f) => withParam('/photos', 'photo', f),
    },
    {
      label: 'Field Reports',
      i18nKey: 'files.module.field_reports',
      description: 'Attach photos to daily field reports',
      descriptionI18nKey: 'files.module.field_reports_desc',
      icon: MapPin,
      route: () => '/field-reports',
    },
  ],
  sheet: [
    {
      label: 'PDF Takeoff',
      i18nKey: 'files.module.pdf_takeoff',
      description: 'Open the parent PDF in the takeoff viewer',
      descriptionI18nKey: 'files.module.pdf_takeoff_desc_sheet',
      icon: Ruler,
      // A sheet row's id is the Sheet PK, but the takeoff viewer resolves
      // `doc` against the DOCUMENTS table, so passing the sheet id 404s and
      // leaves the viewer blank. Open the PARENT document the sheet was
      // extracted from instead - the sheets collector carries that id in the
      // FileRow `extra.document_id`. Fall back to the sheet id only if it is
      // somehow absent (no worse than the old behaviour).
      route: (_p, f, extra) => {
        const parent =
          extra && extra.document_id != null && extra.document_id !== ''
            ? String(extra.document_id)
            : null;
        const doc = parent ?? f;
        return doc
          ? `/takeoff?doc=${encodeURIComponent(doc)}&source=document&tab=measurements`
          : '/takeoff';
      },
    },
    {
      label: 'File Manager',
      i18nKey: 'files.module.documents',
      description: 'See the source PDF this sheet was extracted from',
      descriptionI18nKey: 'files.module.documents_desc_sheet',
      icon: FileText,
      route: (p, f) => withParam(PROJECT(p, 'files'), 'file', f),
    },
  ],
  bim_model: [
    {
      // Primary — opens the model directly in the 3D viewport via the
      // /projects/:projectId/bim/:modelId route (BIMPage.tsx L1496 reads
      // both path params; App.tsx L486).
      label: 'BIM 3D Viewer',
      i18nKey: 'files.module.bim_viewer',
      description: 'Inspect 3D model elements & quantities',
      descriptionI18nKey: 'files.module.bim_viewer_desc',
      icon: Box,
      route: (p, f) => (f ? PROJECT(p, `bim/${encodeURIComponent(f)}`) : PROJECT(p, 'bim')),
    },
    {
      // CAD-BIM BI Explorer — spreadsheet/pivot/chart analytics over the
      // model's element data. Route /data-explorer (App.tsx L475). The
      // page is *session*-based: with no `?session=` it lands on the
      // empty picker. A seeded BIM model has no CAD session, so we pass
      // the model id via `?bimModel=` — the page calls
      // POST /cad-data/from-bim-model to materialise a session from the
      // model's elements, then redirects to `?session=<id>`. The project
      // is also pinned (store + `?project=`) so the workspace stays bound.
      label: 'CAD-BIM BI Explorer',
      i18nKey: 'files.module.cad_bim_explorer',
      description: 'Pivot, chart & analyse element quantities',
      descriptionI18nKey: 'files.module.cad_bim_explorer_desc',
      icon: BarChart3,
      route: (p, f) =>
        f
          ? `/data-explorer?bimModel=${encodeURIComponent(f)}&project=${encodeURIComponent(p)}`
          : `/data-explorer?project=${encodeURIComponent(p)}`,
      setsActiveProject: true,
    },
    {
      // Clash Detection — geometric interference review. Route /clash
      // (App.tsx L482); ClashDetectionPage.tsx resolves the project from
      // the global context store first, falling back to ?project=. We set
      // the store AND pass ?project= so the page opens populated, plus
      // ?model= so this model is pre-selected in the run config.
      label: 'Clash Detection',
      i18nKey: 'files.module.clash_detection',
      description: 'Run geometric interference checks on this model',
      descriptionI18nKey: 'files.module.clash_detection_desc',
      icon: Radar,
      route: (p, f) =>
        f
          ? `/clash?project=${encodeURIComponent(p)}&model=${encodeURIComponent(f)}`
          : `/clash?project=${encodeURIComponent(p)}`,
      setsActiveProject: true,
    },
  ],
  dwg_drawing: [
    {
      label: 'DWG Takeoff',
      i18nKey: 'files.module.dwg_takeoff',
      description: 'Measure quantities from native CAD',
      descriptionI18nKey: 'files.module.dwg_takeoff_desc',
      icon: Pencil,
      route: (_p, f) => withParam('/dwg-takeoff', 'drawingId', f),
    },
    {
      label: 'CAD-BIM BI Explorer',
      i18nKey: 'nav.cad_bim_explorer',
      description: 'Inspect parsed entities, layers & blocks',
      descriptionI18nKey: 'files.module.data_explorer_desc',
      icon: Package,
      route: (_p, f) => withParam('/data-explorer', 'drawingId', f),
    },
  ],
  takeoff: [
    {
      label: 'Takeoff',
      i18nKey: 'files.module.takeoff',
      description: 'Continue measuring or review takeoff results',
      descriptionI18nKey: 'files.module.takeoff_desc',
      icon: Ruler,
      // TakeoffPage reads `doc`/`source`/`tab` (not `session`), so mirror the
      // document-kind builder so the file actually opens in the viewer.
      route: (_p, f) =>
        f
          ? `/takeoff?doc=${encodeURIComponent(f)}&source=document&tab=measurements`
          : '/takeoff',
    },
  ],
  report: [
    {
      label: 'Reports',
      i18nKey: 'files.module.reports',
      description: 'Browse generated cost & validation reports',
      descriptionI18nKey: 'files.module.reports_desc',
      icon: FileBarChart,
      // /reporting reads no query params, so a `?report=` deep-link is dead.
      // Keep the file selected in /files (which reads `?file=`) instead.
      route: (p, f) => withParam(PROJECT(p, 'files'), 'file', f),
    },
  ],
  markup: [
    {
      label: 'Markups',
      i18nKey: 'files.module.markups',
      description: 'Open markups & comment threads',
      descriptionI18nKey: 'files.module.markups_desc',
      icon: PenTool,
      route: (_p, f) => withParam('/markups', 'markup', f),
    },
  ],
};

// DWG/DXF target for a file of the *document* kind. A `document`-kind
// FileRow carries the **Document** id (file_manager_service maps
// ``id=str(Document.id)``), NOT a DwgDrawing id — so the bare
// ``dwg_drawing`` target (which passes the id as ``?drawingId=``) would
// hand DwgTakeoffPage a document id it can never resolve, leaving the
// viewer blank. This passes ``?docId=`` instead, which the page imports a
// drawing from on demand (idempotent backend) and opens immediately.
const DOC_DWG_TAKEOFF: ModuleTarget = {
  ...KIND_MODULES.dwg_drawing[0]!,
  route: (_p, f) => withParam('/dwg-takeoff', 'docId', f),
};

// BIM viewer target for a file of the *document* kind. A `document`-kind
// FileRow carries the **Document** id (file_manager_service maps
// ``id=str(Document.id)``), NOT a BIMModel id - so the bare ``bim_model``
// target (which builds ``/bim/<id>`` and BIMPage reads as a *model* id)
// would 404 with "model not found" and never convert the upload. That is
// issue #273: opening a BIM file uploaded from Project Files did nothing
// because no model exists yet. This passes ``?docId=`` instead, which
// BIMPage turns into a model on demand via createBimModelFromDocument
// (idempotent backend), exactly mirroring the DWG handling above.
const DOC_BIM_VIEWER: ModuleTarget = {
  ...KIND_MODULES.bim_model[0]!,
  route: (p, f) => withParam(PROJECT(p, 'bim'), 'docId', f),
};

// Inline "just read it" viewer for a `document`-kind PDF. This is the new
// DEFAULT open action for PDFs (issue #284): the overwhelming majority of
// project PDFs are contracts, specs, RFI responses and letters that the user
// only wants to read, not measure. It opens the shared InlinePdfPreviewModal
// over the current screen (driven by the ``inlinePreview`` flag) rather than
// navigating away. The ``route`` is a harmless fallback that keeps the file
// selected in /files for any consumer that does not yet honour the flag.
const DOC_PDF_INLINE_VIEW: ModuleTarget = {
  label: 'View',
  i18nKey: 'files.module.view_pdf',
  description: 'Read this PDF here without leaving the page',
  descriptionI18nKey: 'files.module.view_pdf_desc',
  icon: Eye,
  inlinePreview: true,
  route: (p, f) => withParam(PROJECT(p, 'files'), 'file', f),
};

// The PDF Takeoff target for a `document`-kind PDF. No longer the primary
// (see DOC_PDF_INLINE_VIEW) - offered as an explicit secondary so the user
// chooses which PDFs are takeoff plans. Mirrors KIND_MODULES.document[0].
const DOC_PDF_TAKEOFF: ModuleTarget = KIND_MODULES.document[0]!;

// Image extensions that should open in the MediaLightbox image viewer rather
// than fall through to PDF Takeoff (#284 follow-up, ITEM 10). Generic uploads
// land as kind="document" with one of these extensions, so primaryModule used
// to hand them to PDF Takeoff (the document kind's first module), which cannot
// render a raster image. Kept lower-case and bare (no leading dot).
const IMAGE_EXTS = new Set([
  'jpg',
  'jpeg',
  'png',
  'gif',
  'webp',
  'heic',
  'heif',
  'avif',
  'bmp',
  'svg',
  'tiff',
  'tif',
]);

// Video extensions that should open in the MediaLightbox player (#284
// follow-up, ITEM 10). Same rationale as IMAGE_EXTS: a .mp4 upload under the
// document kind must play, not open a takeoff viewer it can never satisfy.
const VIDEO_EXTS = new Set(['mp4', 'mov', 'webm', 'avi', 'mkv', 'm4v']);

// Inline "view it here" image viewer for an image file. The PRIMARY open
// action for an image (#284 follow-up, ITEM 10): it opens the shared
// MediaLightbox overlay (an authed <img>) over the current screen rather than
// navigating away. The ``route`` is a harmless fallback that keeps the file
// selected in /files for any consumer that does not yet honour the flag.
const DOC_IMAGE_VIEW: ModuleTarget = {
  label: 'View',
  i18nKey: 'files.module.view_image',
  description: 'View this image here without leaving the page',
  descriptionI18nKey: 'files.module.view_image_desc',
  icon: ImageIcon,
  mediaPreview: true,
  route: (p, f) => withParam(PROJECT(p, 'files'), 'file', f),
};

// Inline player for a video file - the PRIMARY open action for a clip (#284
// follow-up, ITEM 10). Opens the shared MediaLightbox overlay (an authed
// <video controls>). The ``route`` keeps the file selected in /files as a
// harmless fallback for any consumer that does not yet honour the flag.
const DOC_VIDEO_VIEW: ModuleTarget = {
  label: 'Play',
  i18nKey: 'files.module.play_video',
  description: 'Play this video here without leaving the page',
  descriptionI18nKey: 'files.module.play_video_desc',
  icon: PlayCircle,
  mediaPreview: true,
  route: (p, f) => withParam(PROJECT(p, 'files'), 'file', f),
};

// Extensions that live under the `document` kind but are really BIM source
// files needing on-demand conversion when opened from the File Manager.
const DOC_BIM_EXTS = new Set(['ifc', 'rvt', 'glb', 'gltf']);

// Per-extension override for `document` since a PDF, IFC, RVT, DXF and
// XLSX all live under the `document` kind but route to different
// modules. Returns the *primary* target — the secondary list still
// comes from KIND_MODULES so the user has the full menu. These overrides
// apply ONLY to the `document` kind (enforced in primaryModule): a real
// bim_model / dwg_drawing row carries its own native id and must keep its
// path-based route, so the kind guard stops a model/drawing id from being
// mis-sent as a ``?docId=`` import.
const EXT_PRIMARY_OVERRIDE: Record<string, ModuleTarget> = {
  pdf: DOC_PDF_INLINE_VIEW, // #284: read inline by default; Takeoff is opt-in
  ifc: DOC_BIM_VIEWER,
  rvt: DOC_BIM_VIEWER,
  glb: DOC_BIM_VIEWER,
  gltf: DOC_BIM_VIEWER,
  dwg: DOC_DWG_TAKEOFF,
  dxf: DOC_DWG_TAKEOFF,
  // #284 follow-up (ITEM 10): images view, videos play - never PDF Takeoff.
  // Generated from the extension sets so the two stay the single source of
  // truth for both the primary-action override and the predicates below.
  ...Object.fromEntries([...IMAGE_EXTS].map((ext) => [ext, DOC_IMAGE_VIEW])),
  ...Object.fromEntries([...VIDEO_EXTS].map((ext) => [ext, DOC_VIDEO_VIEW])),
};

// Module list for a `document`-kind DWG/DXF file. Only the DWG Takeoff
// target is offered: it passes ``?docId=`` (the Document id), which the
// page resolves by importing a drawing on demand. (The raw dwg_drawing
// Data Explorer target reads neither docId nor drawingId, so it is not
// surfaced for documents.)
const DOC_DWG_MODULES: ModuleTarget[] = [DOC_DWG_TAKEOFF];

// Module list for a `document`-kind BIM source file (IFC/RVT/...). Only the
// docId-passing BIM viewer is offered: the BI Explorer and Clash targets
// need a real BIMModel id, which this document does not have until the
// viewer converts it on demand, so surfacing them here would hand those
// pages a document id they cannot resolve.
const DOC_BIM_MODULES: ModuleTarget[] = [DOC_BIM_VIEWER];

// Module list for a `document`-kind PDF. Primary is the inline reader; PDF
// Takeoff and the File Manager document target follow as explicit choices,
// so the user decides which PDFs are takeoff plans vs which are just read
// (issue #284). The bare KIND_MODULES.document list still puts PDF Takeoff
// first, so we order this one explicitly here.
const DOC_PDF_MODULES: ModuleTarget[] = [
  DOC_PDF_INLINE_VIEW,
  DOC_PDF_TAKEOFF,
  KIND_MODULES.document[1]!, // File Manager (keep file selected in /files)
];

// Module list for a `document`-kind image. Only the lightbox viewer is
// offered: PDF Takeoff is deliberately ABSENT (it cannot render a raster
// image), which is the whole point of ITEM 10. The File Manager target is
// dropped too since the file is already open in /files. Plain Download stays
// available from the preview pane / context menu independent of this list.
const DOC_IMAGE_MODULES: ModuleTarget[] = [DOC_IMAGE_VIEW];

// Module list for a `document`-kind video - the lightbox player only, with
// PDF Takeoff removed for the same reason as images (ITEM 10).
const DOC_VIDEO_MODULES: ModuleTarget[] = [DOC_VIDEO_VIEW];

export function primaryModule(kind: FileKind, extension?: string | null): ModuleTarget {
  // The per-extension overrides import a document on demand via ``?docId=``,
  // so they apply ONLY to the `document` kind (whose id is a Document id).
  // bim_model / dwg_drawing rows carry their own native id and keep their
  // path-based route - guarding on kind stops a real model/drawing id from
  // being mis-routed as a document import (issue #273).
  if (kind === 'document' && extension) {
    const override = EXT_PRIMARY_OVERRIDE[extension.toLowerCase().replace(/^\./, '')];
    if (override) return override;
  }
  return KIND_MODULES[kind][0]!;
}

export function modulesForKind(kind: FileKind, extension?: string | null): ModuleTarget[] {
  // A `document`-kind DWG/DXF or BIM source file carries the Document id, so
  // its module list must use the docId-passing variants (DOC_DWG_MODULES /
  // DOC_BIM_MODULES) that import on demand, instead of the raw id-based
  // dwg_drawing / bim_model targets that would blank the viewer or 404.
  if (kind === 'document' && extension) {
    const ext = extension.toLowerCase().replace(/^\./, '');
    if (ext === 'dwg' || ext === 'dxf') return DOC_DWG_MODULES;
    if (DOC_BIM_EXTS.has(ext)) return DOC_BIM_MODULES;
    if (ext === 'pdf') return DOC_PDF_MODULES;
    // ITEM 10: images / videos open in the lightbox; PDF Takeoff is removed.
    if (IMAGE_EXTS.has(ext)) return DOC_IMAGE_MODULES;
    if (VIDEO_EXTS.has(ext)) return DOC_VIDEO_MODULES;
  }
  return KIND_MODULES[kind] ?? [];
}

// Normalise a raw extension ("PDF", ".pdf", "pdf") to a bare lower-case token.
function _normExt(extension?: string | null): string {
  return (extension ?? '').toLowerCase().replace(/^\./, '');
}

/**
 * True when a FileRow should open in the inline PDF reader overlay rather
 * than navigate to a module. Drives the open handlers across the File
 * Manager surfaces (grid / list / context-menu / preview pane) and the
 * project-overview recents so a PDF is read in place by default (#284).
 *
 * A row qualifies when its primary target carries the ``inlinePreview``
 * flag AND it actually has a download URL to fetch the bytes from. We also
 * sniff the mime type so a PDF stored without a .pdf extension still reads
 * inline instead of falling through to a takeoff route it can't satisfy.
 */
export function isInlinePreviewRow(row: {
  kind: FileKind;
  extension?: string | null;
  mime_type?: string | null;
  download_url?: string | null;
}): boolean {
  if (!row.download_url) return false;
  const isPdf =
    _normExt(row.extension) === 'pdf' ||
    (row.mime_type ?? '').toLowerCase() === 'application/pdf';
  if (!isPdf) return false;
  // Resolve the primary target as a PDF even when the row carries no .pdf
  // extension - we sniffed the mime type above, so pass an explicit 'pdf' so
  // primaryModule sees the document-PDF inline override instead of falling
  // back to the non-inline default (which keys off the extension alone).
  return Boolean(primaryModule(row.kind, 'pdf').inlinePreview);
}

/** The minimal row shape the media predicates need to classify a file. */
export interface MediaRowLike {
  kind: FileKind;
  extension?: string | null;
  mime_type?: string | null;
  download_url?: string | null;
}

/**
 * True when a file is a raster/vector image, keyed on its extension first and
 * the ``image/*`` mime type as a fallback for uploads stored without a useful
 * extension. Pure classifier - it does NOT consider the download URL, so it is
 * safe to call for icon/label decisions on rows that may not be downloadable.
 */
export function isImageRow(row: MediaRowLike): boolean {
  if (IMAGE_EXTS.has(_normExt(row.extension))) return true;
  return (row.mime_type ?? '').toLowerCase().startsWith('image/');
}

/**
 * True when a file is a video clip, keyed on its extension first and the
 * ``video/*`` mime type as a fallback. Same pure-classifier contract as
 * ``isImageRow``.
 */
export function isVideoRow(row: MediaRowLike): boolean {
  if (VIDEO_EXTS.has(_normExt(row.extension))) return true;
  return (row.mime_type ?? '').toLowerCase().startsWith('video/');
}

/**
 * True when a row should open in the shared ``MediaLightbox`` overlay (an
 * authed <img> for images, an authed <video controls> for clips) rather than
 * navigate to a module. Drives the open handlers across the File Manager
 * surfaces so an image is viewed and a video is played in place, never routed
 * to PDF Takeoff (#284 follow-up, ITEM 10).
 *
 * A row qualifies when it is an image or video AND has a download URL to fetch
 * the bytes from. The ``photo`` kind is intentionally excluded here even
 * though it is an image: it already has a dedicated Site Photos viewer as its
 * primary module, so it is not a takeoff mis-route and keeps its own flow.
 */
export function isLightboxRow(row: MediaRowLike): boolean {
  if (!row.download_url) return false;
  if (row.kind !== 'document') return false;
  return isImageRow(row) || isVideoRow(row);
}

/**
 * The explicit "Open in PDF Takeoff" target for a `document`-kind PDF, or
 * ``null`` for any other row. Surfaces (context menu, preview pane) use this
 * to offer takeoff as a deliberate, separate action now that it is no longer
 * the default open behaviour for PDFs (#284).
 */
export function pdfTakeoffTargetFor(row: {
  kind: FileKind;
  extension?: string | null;
  mime_type?: string | null;
}): ModuleTarget | null {
  const isPdf =
    _normExt(row.extension) === 'pdf' ||
    (row.mime_type ?? '').toLowerCase() === 'application/pdf';
  if (row.kind === 'document' && isPdf) return DOC_PDF_TAKEOFF;
  return null;
}
