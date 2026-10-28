// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "How it works" guide content for the PDF Takeoff module. Pure data,
// consumed by <ModuleGuideButton content={takeoffGuide} />. Every key
// carries its inline English defaultValue; no keys are added to locale
// files (the ModuleGuide reads defaults via t(key, { defaultValue })).

import type { ModuleGuideContent } from '@/shared/ui';

export const takeoffGuide: ModuleGuideContent = {
  titleKey: 'guide.takeoff.title',
  titleDefault: 'PDF Takeoff',
  introKey: 'guide.takeoff.intro',
  introDefault:
    'Takeoff means reading quantities straight off a drawing. Here you upload a PDF plan, set its real-world scale, then measure areas, lengths and counts and send them to your Bill of Quantities.',
  sections: [
    {
      icon: 'Workflow',
      titleKey: 'guide.takeoff.upload.title',
      titleDefault: 'Upload a PDF drawing',
      bodyKey: 'guide.takeoff.upload.body',
      bodyDefault:
        'Drag a PDF floor plan, section or scan onto the drop zone, or click to browse. Vector PDFs measure most precisely, but scanned drawings work too once you calibrate the scale.',
      spotlightSelector: '[data-guide="takeoff-upload"]',
    },
    {
      icon: 'BookOpen',
      titleKey: 'guide.takeoff.calibrate.title',
      titleDefault: 'Set the scale first',
      bodyKey: 'guide.takeoff.calibrate.body',
      bodyDefault:
        'Open the drawing on the Measurements tab and pick the Calibrate tool. Click two points across a known dimension, type its real length, and every later measurement converts to metres or feet. Or choose a preset like 1:50 or 1:100 if the plan states it.',
      spotlightSelector: '#takeoff-tab-measurements',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.takeoff.tools.title',
      titleDefault: 'Measure areas, lengths and counts',
      bodyKey: 'guide.takeoff.tools.body',
      bodyDefault:
        'Use Area for floors and walls, Distance or Polyline for runs of pipe, skirting or kerb, and Count for fittings like doors and sockets. Add a depth to an area to get a volume. Each measurement shows its live quantity and unit.',
      spotlightSelector: '[data-guide="takeoff-tools"]',
      spotlightPosition: 'bottom',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.takeoff.organize.title',
      titleDefault: 'Name and group your measurements',
      bodyKey: 'guide.takeoff.organize.body',
      bodyDefault:
        'Give each measurement a clear description and drop it into a group such as Structural or Finishes. Good names keep the ledger readable and make the BOQ items that follow easy to recognise.',
      spotlightSelector: '[data-testid="measurement-ledger"]',
      spotlightPosition: 'left',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.takeoff.confirm.title',
      titleDefault: 'Confirm into the BOQ',
      bodyKey: 'guide.takeoff.confirm.body',
      bodyDefault:
        'Choose the project and Bill of Quantities at the top, then add the measurements you want. They land as priced positions that stay linked to the drawing, so a revised plan updates the quantity in place.',
      spotlightSelector: '#takeoff-tab-documents',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.takeoff.ai.title',
      titleDefault: 'Let AI do a first pass',
      bodyKey: 'guide.takeoff.ai.body',
      bodyDefault:
        'On the Documents and AI tab you can connect an AI provider and have it read the plan, suggesting elements with quantities and a confidence score. You review every suggestion and confirm the ones you trust before they reach the BOQ.',
      spotlightSelector: '[data-testid="takeoff-ai-setup-notice"]',
    },
  ],
  ctaKey: 'guide.takeoff.cta',
  ctaDefault: 'Upload your first drawing',
};
