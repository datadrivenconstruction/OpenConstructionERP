// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// cadExplorerGuide - "How it works" content for the CAD/BIM Data Explorer.
// Consumed by <ModuleGuideButton content={cadExplorerGuide} /> on
// CadDataExplorerPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const cadExplorerGuide: ModuleGuideContent = {
  titleKey: 'guide.cad_explorer.title',
  titleDefault: 'CAD-BIM BI Explorer',
  introKey: 'guide.cad_explorer.intro',
  introDefault:
    'The CAD-BIM BI Explorer turns the elements extracted from a converted CAD or BIM model into a live spreadsheet you can interrogate. Use it to filter, pivot, chart and describe quantities and parameters without opening the 3D model.',
  sections: [
    {
      icon: 'Database',
      titleKey: 'guide.cad_explorer.load.title',
      titleDefault: 'Load a model session',
      bodyKey: 'guide.cad_explorer.load.body',
      bodyDefault:
        'Drop an IFC, Revit®, DWG or DXF file into the upload card and it is converted locally into element data, or open a model you already have from the BIM hub or Recent Models. Each load becomes a data session with its element rows and parameter columns ready to explore.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.cad_explorer.table.title',
      titleDefault: 'Browse the data table',
      bodyKey: 'guide.cad_explorer.table.body',
      bodyDefault:
        'The Data Table lists every element with its parameters. Sort any column, filter by a value, search across all columns, choose which columns are visible, and switch on the heatmap to read magnitudes at a glance. Null and out-of-range cells are highlighted so gaps stand out.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.cad_explorer.pivot.title',
      titleDefault: 'Pivot and aggregate',
      bodyKey: 'guide.cad_explorer.pivot.body',
      bodyDefault:
        'The Pivot tab groups elements by columns such as storey, discipline or type and aggregates volumes, areas, lengths and counts with sum, average, min, max or count unique. View the result as a table, heatmap, bar chart, treemap or cross-tab matrix.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.cad_explorer.charts.title',
      titleDefault: 'Chart and cross-filter',
      bodyKey: 'guide.cad_explorer.charts.body',
      bodyDefault:
        'The Charts tab visualizes distributions as bar, pie, line or scatter charts. Clicking a bar or slice adds a slicer that filters every tab at once, so a selection you make here narrows the table, pivot and statistics together. The active filter chips show what is in view and clear in one click.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.cad_explorer.describe.title',
      titleDefault: 'Describe and check quality',
      bodyKey: 'guide.cad_explorer.describe.body',
      bodyDefault:
        'The Describe tab gives a statistical summary of every numeric column, including min, max, mean and standard deviation, alongside a missing-data panel that flags columns with empty values. It is the fastest way to sanity-check the model before you rely on the quantities.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.cad_explorer.export.title',
      titleDefault: 'Export, save and reuse',
      bodyKey: 'guide.cad_explorer.export.body',
      bodyDefault:
        'Export the full filtered dataset to CSV, save the current filters, slicers and chart setup as a named view to reopen later, or save the selected elements back as a BIM model you can open in the 3D viewer. Views and sessions stay available from the header so analysis is repeatable.',
    },
  ],
  ctaKey: 'guide.cad_explorer.cta',
  ctaDefault: 'Load a model to begin',
};
