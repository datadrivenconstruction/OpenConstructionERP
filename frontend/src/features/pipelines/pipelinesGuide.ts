// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// pipelinesGuide - "How it works" content for the Pipeline Builder module.
// Consumed by <ModuleGuideButton content={pipelinesGuide} /> on PipelinesPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const pipelinesGuide: ModuleGuideContent = {
  titleKey: 'guide.pipelines.title',
  titleDefault: 'Pipeline Builder',
  introKey: 'guide.pipelines.intro',
  introDefault:
    'The Pipeline Builder is a visual, no-code canvas for automating work across the platform. You drag steps onto the canvas, connect them in order, then run the flow and watch each step finish live.',
  sections: [
    {
      icon: 'Workflow',
      titleKey: 'guide.pipelines.concept.title',
      titleDefault: 'Steps wired into a flow',
      bodyKey: 'guide.pipelines.concept.body',
      bodyDefault:
        'A pipeline is a graph of steps that pass data from one to the next. Each step does one job, and the connections between them decide the order things run in. Build it left to right so the flow reads the way the work actually happens.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.pipelines.palette.title',
      titleDefault: 'Pick steps from the palette',
      bodyKey: 'guide.pipelines.palette.body',
      bodyDefault:
        'The palette on the left groups every step by what it does: triggers that start the flow, steps that get data, transforms, validation gates, AI, and actions that write the result. Drag a step onto the canvas or just click it to drop it in. Use the search box to find one fast.',
      spotlightSelector: '[data-tour="pipeline-palette"]',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.pipelines.connect.title',
      titleDefault: 'Connect the steps',
      bodyKey: 'guide.pipelines.connect.body',
      bodyDefault:
        'Drag from a step output dot to the next step input to wire them together. The colour and shape of each dot show the data type, so only compatible ports connect. Steps that write data carry a writes badge and should sit behind a validation gate.',
      spotlightSelector: '[data-tour="pipeline-canvas"]',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.pipelines.inspector.title',
      titleDefault: 'Configure and check each step',
      bodyKey: 'guide.pipelines.inspector.body',
      bodyDefault:
        'Select a step to open its settings in the inspector on the right. The toolbar flags an issue when a step still needs an input connected, and Explain writes a plain-language summary of every step and how the data flows between them.',
      spotlightSelector: '[data-testid="pipeline-explain"]',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.pipelines.run.title',
      titleDefault: 'Save and run it',
      bodyKey: 'guide.pipelines.run.body',
      bodyDefault:
        'Save keeps your work, and Run executes the pipeline so each step lights up as it finishes. The run dock at the bottom tracks live progress and keeps a history of past runs. Detach hides a run from the canvas while it keeps going in the background.',
      spotlightSelector: '[data-testid="pipeline-run"]',
    },
  ],
  ctaKey: 'guide.pipelines.cta',
  ctaDefault: 'Drop your first step',
};
