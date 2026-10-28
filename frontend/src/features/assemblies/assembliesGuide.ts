// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ModuleGuideContent } from '@/shared/ui';

/**
 * "How it works" guide content for the Assemblies module.
 *
 * Consumed by <ModuleGuideButton content={assembliesGuide} /> in
 * AssembliesPage. Every string is inline-defaulted and read via
 * t(key, { defaultValue }), so the keys are not in en.ts, the inline defaults
 * are the English source; their translations live in the other locale files,
 * so a changed default needs its translations redone too.
 *
 * Spotlight selectors target stable hooks that exist on the /assemblies
 * list page (the data-testid grid and the data-guide action buttons),
 * so the highlight survives Tailwind churn and button reorders.
 */
export const assembliesGuide: ModuleGuideContent = {
  titleKey: 'guide.assemblies.title',
  titleDefault: 'Assemblies',
  introKey: 'guide.assemblies.intro',
  introDefault:
    'An assembly is a reusable cost recipe. It bundles the materials, labour and equipment for a unit of work into one composite rate, so you price recurring work once and reuse it across every estimate.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.assemblies.concept.title',
      titleDefault: 'What an assembly is',
      bodyKey: 'guide.assemblies.concept.body',
      bodyDefault:
        'Think of an assembly as a recipe for one unit of finished work, for example one cubic metre of reinforced concrete wall. It carries a code, a name, a category and a unit, and underneath it a list of component lines that add up to its rate.',
      spotlightSelector: '[data-testid="assemblies-grid"]',
    },
    {
      icon: 'Database',
      titleKey: 'guide.assemblies.components.title',
      titleDefault: 'Components and factors',
      bodyKey: 'guide.assemblies.components.body',
      bodyDefault:
        'Each component is one resource, tagged as material, labour or equipment. The factor is how much of it goes into one unit of the assembly, such as 0.12 tonnes of rebar per cubic metre of concrete. Quantity and Unit Cost complete the line.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.assemblies.rate.title',
      titleDefault: 'How the composite rate is built',
      bodyKey: 'guide.assemblies.rate.body',
      bodyDefault:
        'Every component line is Factor times Quantity times Unit Cost. The lines are summed and then multiplied by the bid factor to give the total rate. The editor also splits the rate into its material, labour and equipment shares so you can see where the cost sits.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.assemblies.entry.title',
      titleDefault: 'Building an assembly step by step',
      bodyKey: 'guide.assemblies.entry.body',
      bodyDefault:
        'Start with New Assembly, give it a code, name, category and unit, then open the editor. Add a component line for each resource, pick its type, and fill in the factor, quantity and unit cost. The line totals and the composite rate recompute as you type.',
      spotlightSelector: '[data-guide="assemblies-new"]',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.assemblies.create.title',
      titleDefault: 'Faster ways to start',
      bodyKey: 'guide.assemblies.create.body',
      bodyDefault:
        'You do not have to build every recipe by hand. Browse Library applies a ready-made template, AI Generate drafts the components from a plain-language description, and Import brings in an assembly exported elsewhere. Each one drops you into the editor to review and adjust.',
      spotlightSelector: '[data-guide="assemblies-ai-generate"]',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.assemblies.apply.title',
      titleDefault: 'Using assemblies in a BOQ',
      bodyKey: 'guide.assemblies.apply.body',
      bodyDefault:
        'Once an assembly is priced, apply it to a Bill of Quantities position to pull its rate and components straight in. Reusing assemblies keeps your rates consistent across the project, and the usage count shows you which recipes earn their keep.',
    },
  ],
  ctaKey: 'guide.assemblies.cta',
  ctaDefault: 'Create your first assembly',
};
