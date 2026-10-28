// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog — Takeoff & quantities + Reality capture domains.
// See ../types.ts for the ModuleExplanation shape and the key convention.

import type { ModuleExplanation } from '../types';

export const takeoffRealityModules: ModuleExplanation[] = [
  /* ── Takeoff & quantities ─────────────────────────────────────────────── */
  {
    id: 'quantities',
    route: '/quantities',
    icon: 'Ruler',
    category: 'takeoff',
    titleKey: 'howto.quantities.title',
    titleDefault: 'Quantity Takeoff',
    summaryKey: 'howto.quantities.summary',
    summaryDefault: 'The central list of measured quantities, gathered from every source.',
    whatKey: 'howto.quantities.what',
    whatDefault:
      'Quantity Takeoff is where measured quantities live, no matter where they came from - PDF, CAD, BIM or manual entry. It is the bridge between measuring the work and pricing it, feeding clean quantities into the BOQ.',
    how: [
      { key: 'howto.quantities.how.1', default: 'Collect quantities by measuring in the PDF, DWG or BIM tools, or add them by hand.' },
      { key: 'howto.quantities.how.2', default: 'Group and label them so each quantity maps cleanly to a BOQ position.' },
      { key: 'howto.quantities.how.3', default: 'Send confirmed quantities into the BOQ to be priced.' },
    ],
    tips: [
      { key: 'howto.quantities.tip.1', default: 'Keep the unit consistent with the BOQ position you will map to, so totals line up without conversion surprises.' },
    ],
  },
  {
    id: 'takeoff',
    route: '/takeoff',
    icon: 'PencilRuler',
    category: 'takeoff',
    keywords: 'pdf measure scale calibrate area length count drawing',
    titleKey: 'howto.takeoff.title',
    titleDefault: 'PDF Takeoff',
    summaryKey: 'howto.takeoff.summary',
    summaryDefault: 'Measure lengths, areas and counts directly on a PDF drawing.',
    whatKey: 'howto.takeoff.what',
    whatDefault:
      'PDF Takeoff lets you measure straight on a drawing. Calibrate the scale once, then draw lengths, areas and counts on top of the sheet; each measurement becomes a quantity you can carry into the estimate.',
    how: [
      { key: 'howto.takeoff.how.1', default: 'Open a PDF and calibrate the scale with the two-click tool against a known dimension (the tool can also detect the scale for you).' },
      { key: 'howto.takeoff.how.2', default: 'Pick a measure tool - length, area or count - and trace the items on the sheet.' },
      { key: 'howto.takeoff.how.3', default: 'Use the thumbnail sidebar and find-on-sheet search to move between pages quickly.' },
      { key: 'howto.takeoff.how.4', default: 'Add the measurements to your BOQ as quantities.' },
    ],
    tips: [
      { key: 'howto.takeoff.tip.1', default: 'Always calibrate before measuring - an uncalibrated sheet gives confident but wrong numbers.' },
      { key: 'howto.takeoff.tip.2', default: 'Measurements are saved per drawing, so you can leave and come back without losing your markups.' },
    ],
  },
  {
    id: 'dwg-takeoff',
    route: '/dwg-takeoff',
    icon: 'PencilRuler',
    category: 'takeoff',
    keywords: 'cad dwg layer block count auto quantify text',
    titleKey: 'howto.dwg-takeoff.title',
    titleDefault: 'DWG Takeoff',
    summaryKey: 'howto.dwg-takeoff.summary',
    summaryDefault: 'Measure and auto-quantify straight from CAD drawings by layer and block.',
    whatKey: 'howto.dwg-takeoff.what',
    whatDefault:
      'DWG Takeoff reads CAD drawings and lets you measure on real vector geometry. Because the drawing is structured, you can auto-quantify by layer, count repeated blocks and pull text - far faster and more exact than tracing a flat PDF.',
    how: [
      { key: 'howto.dwg-takeoff.how.1', default: 'Open a DWG; the layers and blocks come through as selectable structure.' },
      { key: 'howto.dwg-takeoff.how.2', default: 'Use Count to tally repeated blocks, or auto-quantify whole layers in one step.' },
      { key: 'howto.dwg-takeoff.how.3', default: 'Build a BOQ from a selected group and export it, or send quantities onward to the estimate.' },
      { key: 'howto.dwg-takeoff.how.4', default: 'Find text on the drawing to locate rooms, tags and notes.' },
    ],
    tips: [
      { key: 'howto.dwg-takeoff.tip.1', default: 'Clean, well-layered CAD pays off here - auto-quantify is only as good as the drawing structure.' },
    ],
  },
  {
    id: 'bim',
    route: '/bim',
    icon: 'Box',
    category: 'takeoff',
    keywords: 'ifc model 3d viewer elements properties storey',
    titleKey: 'howto.bim.title',
    titleDefault: 'BIM Viewer',
    summaryKey: 'howto.bim.summary',
    summaryDefault: 'Open 3D models, inspect elements and pull quantities from the model.',
    whatKey: 'howto.bim.what',
    whatDefault:
      'The BIM Viewer opens IFC and converted models in 3D. Every element carries its properties and quantities, so you can search, filter and select parts of the building and read measured quantities straight off the model.',
    how: [
      { key: 'howto.bim.how.1', default: 'Open a model file; navigate, orbit and section it in 3D.' },
      { key: 'howto.bim.how.2', default: 'Search and filter elements by type, level or property to isolate what you care about.' },
      { key: 'howto.bim.how.3', default: 'Read element quantities and properties, and carry selected quantities into takeoff or matching.' },
    ],
    tips: [
      { key: 'howto.bim.tip.1', default: 'Use the converters to turn proprietary CAD/BIM files into open model data the viewer can read.' },
    ],
  },
  {
    id: 'data-explorer',
    route: '/data-explorer',
    icon: 'Database',
    category: 'takeoff',
    keywords: 'cad bim dataframe table elements properties export',
    // #149: this entry deliberately reads the nav key rather than its own
    // howto.data-explorer.title, so the article is headed the same name the
    // sidebar and the page itself use. The howto.* key held a second name.
    titleKey: 'nav.cad_bim_explorer',
    titleDefault: 'CAD-BIM BI Explorer',
    summaryKey: 'howto.data-explorer.summary',
    summaryDefault: 'See a model as a filterable table of elements, properties and quantities.',
    whatKey: 'howto.data-explorer.what',
    whatDefault:
      'Data Explorer presents a converted CAD or BIM model as a spreadsheet-like table: one row per element, with all its properties and quantities as columns. It is the fastest way to slice, filter and export model data without 3D navigation.',
    how: [
      { key: 'howto.data-explorer.how.1', default: 'Load a converted model; every element becomes a row you can sort and filter.' },
      { key: 'howto.data-explorer.how.2', default: 'Filter by type or property to isolate the elements you want to quantify.' },
      { key: 'howto.data-explorer.how.3', default: 'Export the filtered table, or pass it to matching to price the elements.' },
    ],
  },

  /* ── Reality capture & 3D ─────────────────────────────────────────────── */
  {
    id: 'geo',
    route: '/geo',
    icon: 'Map',
    category: 'reality',
    beta: true,
    keywords: 'gis map geospatial overlay site location',
    titleKey: 'howto.geo.title',
    titleDefault: 'Geo Hub',
    summaryKey: 'howto.geo.summary',
    summaryDefault: 'Put the project on the map with site boundaries and geospatial overlays.',
    whatKey: 'howto.geo.what',
    whatDefault:
      'Geo Hub places your project in the real world on a map. Add site boundaries, layers and overlays to give spatial context to the work - useful for siting, logistics and anyone who thinks in locations rather than drawings.',
    how: [
      { key: 'howto.geo.how.1', default: 'Open the map and centre it on the project location.' },
      { key: 'howto.geo.how.2', default: 'Add overlays and boundaries to mark the site and areas of interest.' },
      { key: 'howto.geo.how.3', default: 'Use the admin tools to manage which layers and sources are available.' },
    ],
  },
  {
    id: 'pointcloud',
    route: '/pointcloud',
    icon: 'Mountain',
    category: 'reality',
    beta: true,
    keywords: 'point cloud las laz copc scan reality capture as-built',
    titleKey: 'howto.pointcloud.title',
    titleDefault: 'Point Cloud',
    summaryKey: 'howto.pointcloud.summary',
    summaryDefault: 'View laser-scan reality data of the site as it actually is.',
    whatKey: 'howto.pointcloud.what',
    whatDefault:
      'Point Cloud opens laser-scan and photogrammetry data - the site captured as millions of measured points. It is the ground truth of what is really built, useful for checking design against reality and for as-built records.',
    how: [
      { key: 'howto.pointcloud.how.1', default: 'Load a supported scan file (LAS, LAZ or COPC); the viewer streams the points in 3D.' },
      { key: 'howto.pointcloud.how.2', default: 'Navigate the cloud to inspect the captured conditions.' },
      { key: 'howto.pointcloud.how.3', default: 'Compare what you see against the design model to spot differences.' },
    ],
    tips: [
      { key: 'howto.pointcloud.tip.1', default: 'The viewer is honest about formats - if a file is not a supported point-cloud type it tells you rather than failing silently.' },
    ],
  },
];
