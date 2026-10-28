// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// modulesGuide - "How it works" content for the Modules workspace.
// Consumed by <ModuleGuideButton content={modulesGuide} /> on ModulesPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const modulesGuide: ModuleGuideContent = {
  titleKey: 'guide.modules.title',
  titleDefault: 'Modules',
  introKey: 'guide.modules.intro',
  introDefault:
    'The Modules workspace is where you shape the platform around one company: choose a profile to control which tools appear in the sidebar, apply a pack for a ready-made country, industry or partner setup, and install data packages such as cost databases and catalogues. Open it whenever you need to add a capability or trim the menu down to what a team actually uses.',
  sections: [
    {
      icon: 'Workflow',
      titleKey: 'guide.modules.overview.title',
      titleDefault: 'Four tabs, one workspace',
      bodyKey: 'guide.modules.overview.body',
      bodyDefault:
        'The page is split into four tabs: Company Profiles, Packs, Data Packages and System Modules. Profiles and Packs configure which features show up, Data Packages installs content from the marketplace, and System Modules lists the backend plugins currently loaded so you can see what is active.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.modules.profiles.title',
      titleDefault: 'Company Profiles',
      bodyKey: 'guide.modules.profiles.body',
      bodyDefault:
        'A profile is a preset for a type of company that switches a whole set of modules on at once and hides the rest from the sidebar. Pick the card that best matches the business and confirm to apply it; the active profile is shown at the top with its module count.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.modules.toggles.title',
      titleDefault: 'Fine-tune individual modules',
      bodyKey: 'guide.modules.toggles.body',
      bodyDefault:
        'Below the profile cards, the Active Modules list lets you turn single features on or off, grouped by area. A module that other enabled modules depend on cannot be switched off until its dependents are disabled first, so the menu never ends up with broken links.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.modules.packs.title',
      titleDefault: 'Packs',
      bodyKey: 'guide.modules.packs.body',
      bodyDefault:
        'A pack is a ready-made preset for a country, industry, partner or showcase that bundles currency, tax template, reference standards, default modules and optional co-branding. Press Activate to apply one, and switch back any time. Administrators can also install a pack by uploading its .zip or rescanning the data directory.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.modules.data_packages.title',
      titleDefault: 'Data Packages',
      bodyKey: 'guide.modules.data_packages.body',
      bodyDefault:
        'This tab is the marketplace for installable content: regional resource catalogues, cost databases, vector search indices, demo projects, languages, CAD converters and integrations. Filter by category or search, then install with one click; what is already on this instance is summarised under Installed Packages.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.modules.system.title',
      titleDefault: 'System Modules',
      bodyKey: 'guide.modules.system.body',
      bodyDefault:
        'System Modules shows every backend plugin loaded on the server, with its version, dependencies and whether it is core or optional. Core modules are locked, and administrators can enable or disable the non-core ones; disabling may need an app restart, so the change is confirmed first.',
    },
  ],
  ctaKey: 'guide.modules.cta',
  ctaDefault: 'Choose a company profile',
};
