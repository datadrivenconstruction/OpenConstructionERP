// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// dwgTakeoffGuide - "How it works" content for the DWG Takeoff module.
// Consumed by <ModuleGuideButton content={dwgTakeoffGuide} /> on DwgTakeoffPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const dwgTakeoffGuide: ModuleGuideContent = {
  titleKey: 'guide.dwg_takeoff.title',
  titleDefault: 'DWG Takeoff',
  introKey: 'guide.dwg_takeoff.intro',
  introDefault:
    'DWG Takeoff opens 2D DWG drawings so you can measure areas, lengths and counts straight off the plan and feed those quantities into your estimate. Use it when your scope lives in DWG or DXF sheets rather than a 3D model.',
  sections: [
    {
      icon: 'Rocket',
      titleKey: 'guide.dwg_takeoff.upload.title',
      titleDefault: 'Upload a drawing',
      bodyKey: 'guide.dwg_takeoff.upload.body',
      bodyDefault:
        'Drop a DWG or DXF file onto the upload area or click to browse. The file is converted to viewable entities on your own server through the DDC Converters 2.0 pipeline, so it never leaves your environment. DWG 2000 to 2025 and DXF R12 to R2025 are supported.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.dwg_takeoff.layers.title',
      titleDefault: 'Layers and entities',
      bodyKey: 'guide.dwg_takeoff.layers.body',
      bodyDefault:
        'Once the drawing is open every entity is grouped by its CAD layer. Use the Layers tab to toggle layers on and off and filter by entity type so you isolate just the walls, slabs or pipework you want to measure. Click any entity to read its type, layer and computed quantity.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.dwg_takeoff.scale.title',
      titleDefault: 'Set the scale',
      bodyKey: 'guide.dwg_takeoff.scale.body',
      bodyDefault:
        'A drawing is just pixels until you tell it the scale. Open the Scale tab and pick a preset ratio such as 1:50 or 1:100, calibrate by clicking two points and entering the real distance between them, or set a per-annotation scale for detail views on the same sheet. Every measurement then reports in real-world units.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.dwg_takeoff.measure.title',
      titleDefault: 'Measure and annotate',
      bodyKey: 'guide.dwg_takeoff.measure.body',
      bodyDefault:
        'Pick a tool from the floating palette to measure an area, a length or a perimeter, or to drop a note directly on the drawing. Snap to endpoints and midpoints keeps your clicks precise, and Undo or Redo steps you back through any mistake. Saved measurements live under the Notes tab.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.dwg_takeoff.link_boq.title',
      titleDefault: 'Link quantities to the BOQ',
      bodyKey: 'guide.dwg_takeoff.link_boq.body',
      bodyDefault:
        'Select an entity or measurement and link it to a Bill of Quantities position, either picking an existing line or creating a new one. The quantity flows straight into your cost estimate, keeping the BOQ tied back to the exact place on the drawing it came from.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.dwg_takeoff.review.title',
      titleDefault: 'Review, compare and export',
      bodyKey: 'guide.dwg_takeoff.review.body',
      bodyDefault:
        'The Summary tab rolls up total entities, area and length so you can sanity-check the takeoff at a glance. Compare two revisions to see what changed with a cost delta, export measurements to CSV, or save the current viewport to PDF for the record.',
    },
  ],
  ctaKey: 'guide.dwg_takeoff.cta',
  ctaDefault: 'Upload a drawing to begin',
};
