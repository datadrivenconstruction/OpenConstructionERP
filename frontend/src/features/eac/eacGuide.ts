// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// eacGuide - "How it works" content for the EAC block editor module.
// Consumed by <ModuleGuideButton content={eacGuide} /> on EACBlockEditorPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const eacGuide: ModuleGuideContent = {
  titleKey: 'guide.eac.title',
  titleDefault: 'EAC Block Editor',
  introKey: 'guide.eac.intro',
  introDefault:
    'EAC stands for Element, Attribute, Constraint. It is a visual editor where you build model checking and quantity rules by dragging blocks onto a canvas, no code required. Use it to define which elements a rule applies to and what each one must satisfy.',
  sections: [
    {
      icon: 'Lightbulb',
      titleKey: 'guide.eac.concept.title',
      titleDefault: 'What an EAC rule is',
      bodyKey: 'guide.eac.concept.body',
      bodyDefault:
        'A rule picks a set of model elements, then tests each one against conditions on its attributes. You assemble it from blocks instead of writing logic by hand. Every rule produces one of four results: an aggregate value such as a quantity, a pass or fail check, a clash, or an issue.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.eac.palette.title',
      titleDefault: 'The block palette',
      bodyKey: 'guide.eac.palette.body',
      bodyDefault:
        'The left palette holds every block grouped into Selectors, Logic, Triplet, Attributes, Constraints, Variables and Templates. Search to find a block fast, then drag it onto the canvas. Templates drop a ready-made starter such as external wall thickness so you do not begin from scratch.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.eac.selectors.title',
      titleDefault: 'Selectors define the set',
      bodyKey: 'guide.eac.selectors.body',
      bodyDefault:
        'Start with a selector to decide which elements the rule targets. Match by IFC class, Revit® category, classification code such as Uniformat or DIN, or by spatial container like level, zone or room. Combine selectors with AND, OR and NOT logic to narrow the set precisely.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.eac.triplets.title',
      titleDefault: 'Attributes, constraints and variables',
      bodyKey: 'guide.eac.triplets.body',
      bodyDefault:
        'A triplet pairs an attribute with a constraint, for example wall thickness greater than or equal to 240 mm. Reference a property directly, through an alias, or by regex pattern, and choose from operators covering equality, ranges, sets, text and unit-aware comparisons. Local variables aggregate matched values with sum, average, count, min or max.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.eac.canvas.title',
      titleDefault: 'Wiring blocks on the canvas',
      bodyKey: 'guide.eac.canvas.body',
      bodyDefault:
        'Drop blocks onto the canvas and connect their slots to wire the rule together. Drag to reposition, select to multi-edit, and use Undo, Redo, copy and paste plus Delete to refine the layout. Fit view recenters everything when the graph grows.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.eac.run.title',
      titleDefault: 'Save, validate and compile',
      bodyKey: 'guide.eac.run.body',
      bodyDefault:
        'When the rule looks right, Save layout to persist your work. Validate checks the rule for errors before you rely on it, and Compile turns the blocks into the executable plan that runs against your models.',
    },
  ],
  ctaKey: 'guide.eac.cta',
  ctaDefault: 'Drag a selector onto the canvas',
};
