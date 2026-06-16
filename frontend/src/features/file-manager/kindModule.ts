import { BarChart3, Box, FileBarChart, FileText, Image as ImageIcon, MapPin, Package, Pencil, PenTool, Radar, Ruler, type LucideIcon } from 'lucide-react';
import { buildProjectDocumentTakeoffUrl } from '@/features/takeoff/takeoffRoutes';
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
  /** Path template — `{projectId}` is substituted in by the consumer. */
  route: (projectId: string, fileId?: string, file?: FileRouteContext) => string;
  /**
   * Some destinations (Clash Detection, CAD-BIM BI Explorer) resolve the
   * project from the global project-context store rather than from a path
   * param, so they'd land on the empty "no project" state when reached via
   * a deep-link. When this flag is set the consumer must call
   * `useProjectContextStore.setActiveProject(...)` for the file's project
   * BEFORE navigating so the destination opens populated.
   */
  setsActiveProject?: boolean;
}

const PROJECT = (p: string, sub: string) => `/projects/${p}/${sub}`;

export interface FileRouteContext {
  id: string;
  name: string;
  kind: FileKind;
  extension?: string | null;
  extra?: Record<string, unknown>;
}

// Append a deep-link query parameter only when we actually have a file
// id. Keeping the bare path when it's missing avoids URLs like
// `/takeoff?doc=` that some routers parse as an empty string.
const withParam = (path: string, key: string, value?: string): string =>
  value ? `${path}${path.includes('?') ? '&' : '?'}${key}=${encodeURIComponent(value)}` : path;

function pdfTakeoffRoute(_projectId: string, fileId?: string, file?: FileRouteContext): string {
  if (!fileId) return '/takeoff';
  return buildProjectDocumentTakeoffUrl({
    id: fileId,
    name: file?.name ?? 'Document',
    metadata: file?.extra,
  });
}

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
      route: pdfTakeoffRoute,
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
      // TakeoffPage reads `doc`/`source`/`tab` (not `sheet`), so mirror the
      // document-kind builder: open the source PDF with the measurements tab.
      route: pdfTakeoffRoute,
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
      label: 'Data Explorer',
      i18nKey: 'files.module.data_explorer',
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
      route: pdfTakeoffRoute,
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

// Per-extension override for `document` since a PDF, IFC, RVT, DXF and
// XLSX all live under the `document` kind but route to different
// modules. Returns the *primary* target — the secondary list still
// comes from KIND_MODULES so the user has the full menu.
const EXT_PRIMARY_OVERRIDE: Record<string, ModuleTarget> = {
  pdf: KIND_MODULES.document[0]!, // PDF Takeoff
  ifc: KIND_MODULES.bim_model[0]!,
  rvt: KIND_MODULES.bim_model[0]!,
  dgn: KIND_MODULES.bim_model[0]!,
  glb: KIND_MODULES.bim_model[0]!,
  gltf: KIND_MODULES.bim_model[0]!,
  dwg: DOC_DWG_TAKEOFF,
  dxf: DOC_DWG_TAKEOFF,
};

// Module list for a `document`-kind DWG/DXF file. Only the DWG Takeoff
// target is offered: it passes ``?docId=`` (the Document id), which the
// page resolves by importing a drawing on demand. (The raw dwg_drawing
// Data Explorer target reads neither docId nor drawingId, so it is not
// surfaced for documents.)
const DOC_DWG_MODULES: ModuleTarget[] = [DOC_DWG_TAKEOFF];

export function primaryModule(kind: FileKind, extension?: string | null): ModuleTarget {
  if (extension) {
    const override = EXT_PRIMARY_OVERRIDE[extension.toLowerCase().replace(/^\./, '')];
    if (override) return override;
  }
  return KIND_MODULES[kind][0]!;
}

export function modulesForKind(kind: FileKind, extension?: string | null): ModuleTarget[] {
  // A `document`-kind DWG/DXF carries the Document id, so its module list
  // must use the docId-passing variants (see DOC_DWG_MODULES) instead of the
  // raw drawingId-based dwg_drawing targets that would blank the viewer.
  if (kind === 'document' && extension) {
    const ext = extension.toLowerCase().replace(/^\./, '');
    if (ext === 'dwg' || ext === 'dxf') return DOC_DWG_MODULES;
  }
  return KIND_MODULES[kind] ?? [];
}
